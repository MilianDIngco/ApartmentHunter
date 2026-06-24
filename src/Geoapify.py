import requests
from .Models import Coordinate, QuotaExhaustedError, RateLimiting

#TODO implement pagination
#TODO add custom categories

class Geoapify:
    requestLimit: RateLimiting
    apiKey: str
    MAX_REQUESTS: int = 5

    def __init__(self, apiKey: str):
        self.requestLimit = RateLimiting(
                    delay=(1/5),
                    lastRequest=0,
                    lastFail=0,
                    nFail=0,
                    minDelay=(1/5),
                    maxDelay=60,
                    base=2
                )
        self.apiKey = apiKey

    def buildURL(self, latitude: float, longitude: float, radiusMiles: float, category: str) -> str:
        radiusMeters = radiusMiles * 1609.34
        url = f"https://api.geoapify.com/v2/places?categories={category}&filter=circle:{longitude},{latitude},{radiusMeters}&bias=proximity:{longitude},{latitude}&limit=1&apiKey={self.apiKey}"

        if (len(url) > 2048):
            print("ERROR: URL exceeds maximum URL length")
            exit(1)
        return url

    def requestPOI(self, latitude: float, longitude: float, radiusMiles: float, category: str) -> Coordinate:
        # throttle
        self.requestLimit.waitIfTooFast()

        URL = self.buildURL(latitude=latitude, longitude=longitude, radiusMiles=radiusMiles, category=category)

        response = requests.get(URL, timeout=60)
        self.requestLimit.justCalled()
        response.raise_for_status()

        features = response.json().get("features", [])
        if not (features and
                isinstance(features, list) and 
                features[0].get("properties") and 
                features[0].get("properties").get("lon") and 
                features[0].get("properties").get("lat")):
            raise ValueError(f"Geoapify returned POI with unexpected form: {response.json()}")

        poi = features[0]["properties"]
        location = Coordinate(longitude=poi["lon"], latitude=poi["lat"])
        
        return location

    def grabPOI(self, latitude: float, longitude: float, radiusMiles: float, category: str) -> Coordinate:
        for _ in range(self.MAX_REQUESTS):
            try:
                poi = self.requestPOI(latitude=latitude, longitude=longitude, radiusMiles=radiusMiles, category=category)
                self.requestLimit.succeeded()
                return poi
            except requests.exceptions.HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")  # e.g., 404 Not Found or 500 Server Error
                self.requestLimit.failed()
            except requests.exceptions.ConnectionError:
                print("Network error: Failed to connect to the server.")
                self.requestLimit.failed()
            except requests.exceptions.Timeout:
                print("Timeout error: The request took too long.")
                self.requestLimit.failed()
            except requests.exceptions.RequestException as err:
                print(f"A generic requests error occurred: {err}")
                self.requestLimit.failed()
            except ValueError as err:
                print(f"Unexpected value: {err}")
                raise ValueError from err

        # if it gets to this point, its not that it doesn't exist
        # its that the api is unavailable, at which point the program should
        # cache all successful processed listings and stop
        raise QuotaExhaustedError("Geoapify API is unavailable")

    def findPOIs(self, latitude: float, longitude: float, radiusMiles: float, poiCategories: list[str]) -> dict[str, Coordinate]:
        pois = {}
        for category in poiCategories:
            name = category.split(".")[-1]
            try:
                pois[name] = self.grabPOI(
                        latitude=latitude, longitude=longitude,
                        radiusMiles=radiusMiles, category=category
                    )
            except ValueError as err:
                raise ValueError from err
            except QuotaExhaustedError as err:
                raise QuotaExhaustedError from err

        return pois


import time
import requests
from .Models import Coordinate

#TODO implement pagination
#TODO add custom categories

class Geoapify:
    lastRequest: float
    delay: float
    nSuccess: int
    apiKey: str

    def __init__(self, apiKey: str):
        self.lastRequest = 0
        self.delay = 0.2
        self.nSuccess = 0
        self.apiKey = apiKey

    def buildURL(self, latitude: float, longitude: float, radiusMiles: float, category: str) -> str:
        radiusMeters = radiusMiles * 1609.34
        url = f"https://api.geoapify.com/v2/places?categories={category}&filter=circle:{longitude},{latitude},{radiusMeters}&bias=proximity:{longitude},{latitude}&limit=1&apiKey={self.apiKey}"

        if (len(url) > 2048):
            print("ERROR: URL exceeds maximum URL length")
            exit(1)
        return url

    def findPOI(self, latitude: float, longitude: float, radiusMiles: float, category: str) -> Coordinate | None:
        # throttle
        elapsed = time.time() - self.lastRequest 
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

        URL = self.buildURL(latitude=latitude, longitude=longitude, radiusMiles=radiusMiles, category=category)

        try:
            response = requests.get(URL, timeout=60)
            response.raise_for_status()
            self.lastRequest = time.time()

            self.nSuccess += 1
            
            if self.nSuccess > 50:
                self.delay = max(self.delay / 2, .2)
            
            features = response.json().get("features", [])
            if not features:
                return None

            poi = features[0]["properties"]
            location = Coordinate(longitude=poi["lon"], latitude=poi["lat"])
            
            return location
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")  # e.g., 404 Not Found or 500 Server Error
        except requests.exceptions.ConnectionError:
            print("Network error: Failed to connect to the server.")
        except requests.exceptions.Timeout:
            print("Timeout error: The request took too long.")
        except requests.exceptions.RequestException as err:
            print(f"A generic requests error occurred: {err}")

        self.nSuccess = 0
        self.delay = max(self.delay + 1, 10)
        return None

    def findPOIs(self, latitude: float, longitude: float, radiusMiles: float) -> dict:
        pois = {}
        pois["Park"] = self.findPOI(latitude=latitude, longitude=longitude, radiusMiles=radiusMiles, category="leisure.park")
        pois["Supermarket"] = self.findPOI(latitude=latitude, longitude=longitude, radiusMiles=radiusMiles, category="commercial.supermarket")
        pois["Library"] = self.findPOI(latitude=latitude, longitude=longitude, radiusMiles=radiusMiles, category="education.library")

        return pois
        


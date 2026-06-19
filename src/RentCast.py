import json
import requests
import time

class RentCast:
    delay: float
    lastRequest: float
    apiKey: str
    listings: list
    latitude: float
    longitude: float 
    radiusMiles: float
    requestLimit: int
    nRequests: int

    def __init__(self, apiKey: str, latitude: float, longitude: float, radiusMiles: float, requestLimit: int) -> None:
        self.apiKey = apiKey
        self.latitude = latitude
        self.longitude = longitude
        self.radiusMiles = radiusMiles
        self.requestLimit = requestLimit
        self.nRequests = 0
        self.lastRequest = 0
        self.delay = 1 # Not sure about this, probably should double check the rates for rentcast
        self.listings = [] # Initialize listings bc if it isn't set from a cache, it's accessed later w/o being init

    def loadCache(self, cacheFilename) -> bool:
        try:
            with open(cacheFilename, "r") as f:
                cache = json.load(f)
                cacheLatitude = cache.get("latitude", 1000) # coordinates can't physically be > 90 or < -90
                cacheLongitude = cache.get("longitude", 1000)
                cacheRadiusMiles = cache.get("radiusMiles", -1) # radius obv can't be neg
                cacheListings = cache.get("listings", [])
                if cacheLatitude != self.latitude or cacheLongitude != self.longitude or cacheRadiusMiles != self.radiusMiles or len(cacheListings) == 0:
                    print("ERROR: Previous cached listings don't match current search")
                    return False
                else:
                    self.listings = cacheListings
                    return True
        except FileNotFoundError:
            print(f"ERROR: {cacheFilename} was not found")
            return False

    def setTempAsListings(self, tempFilename) -> bool:
        try: 
            with open(f"lib/{tempFilename}", "r") as f:
                self.listings = json.load(f)
                return True
        except FileNotFoundError:
            print(f"ERROR: lib/{tempFilename} not found")
            return False

    def requestAllListings(self):
        while (self.requestListings()):
            print(f"Gathered {len(self.listings)} listings")

    def cacheListings(self, cacheFilename: str):
        # Cache listings as json file
        cache = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "radiusMiles": self.radiusMiles,
            "listings": self.listings
        }
        try: 
            with open(cacheFilename, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=4)
            return True
        except FileNotFoundError:
            print(f"ERROR: {cacheFilename} not found")
            return False


    def buildURL(self, latitude: float, longitude: float, radiusMiles: float) -> str:
        url = f"https://api.rentcast.io/v1/listings/rental/long-term?latitude={latitude}&longitude={longitude}&radius={radiusMiles}&status=Active&limit=500&includeTotalCount=true&offset={len(self.listings)}"
        if (len(url) > 2048):
            raise ValueError("ERROR: URL exceeds maximum URL length")
        return url

    def requestListings(self) -> bool:
        if self.nRequests >= self.requestLimit:
            return False
        # throttle
        elapsed = time.time() - self.lastRequest 
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

        try: 
            url = self.buildURL(self.latitude, self.longitude, self.radiusMiles)
            
            headers = {
                "accept": "application/json", 
                "X-Api-Key": self.apiKey 
            }

            response = requests.get(url, headers=headers, timeout=60)

            self.lastRequest = time.time()

            response.raise_for_status()

            data = response.json() 
            if not isinstance(data, list):
                raise ValueError("ERROR: Unexpected Rentcast response format")

            self.nRequests += 1
            self.listings += response.json()

            # Returning false indicates that there are no more listings in that area. 
            # Returning true indicates that there are more listings in that area
            total = int(response.headers.get("X-Total-Count", "0"))
            return len(self.listings) < total

        # TODO Need to handle exceptions better rather than just dipping lol
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")  # e.g., 404 Not Found or 500 Server Error
            return False
        except requests.exceptions.ConnectionError:
            print("Network error: Failed to connect to the server.")
            return False
        except requests.exceptions.Timeout:
            print("Timeout error: The request took too long.")
            return False
        except requests.exceptions.RequestException as err:
            print(f"A generic requests error occurred: {err}")
            return False
    

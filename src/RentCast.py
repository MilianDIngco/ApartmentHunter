import json
import requests
import os
from pathlib import Path
from .Models import RateLimiting

class RentCast:
    apiLimit: RateLimiting
    nRequests: int
    requestLimit: int
    apiKey: str
    latitude: float
    longitude: float 
    radiusMiles: float
    listings: list
    completed: bool

    def __init__(self, apiKey: str, latitude: float, longitude: float, radiusMiles: float, requestLimit: int) -> None:
        self.apiLimit = RateLimiting(
                    delay=(1/20),
                    lastRequest=0,
                    lastFail=0,
                    nFail=0,
                    minDelay=(1/20),
                    maxDelay=60,
                    base=2
                )
        self.apiKey = apiKey
        self.latitude = latitude
        self.longitude = longitude
        self.radiusMiles = radiusMiles
        self.requestLimit = requestLimit
        self.nRequests = 0
        self.completed = False
        self.listings = [] # Initialize listings bc if it isn't set from a cache, it's accessed later w/o being init

    def loadCache(self, cacheFilename) -> bool:
        try:
            with open(f"cache/{cacheFilename}", "r") as f:
                cache = json.load(f)
                cacheCompleted = cache.get("completed", False)
                cacheLatitude = cache.get("latitude", 1000) # coordinates can't physically be > 90 or < -90
                cacheLongitude = cache.get("longitude", 1000)
                cacheRadiusMiles = cache.get("radiusMiles", -1) # radius obv can't be neg
                cacheListings = cache.get("listings", [])
                if (cacheLatitude != self.latitude or 
                        cacheLongitude != self.longitude or
                        cacheRadiusMiles != self.radiusMiles or
                        len(cacheListings) == 0):
                    print("ERROR: Previous cached listings don't match current search")
                    return False
                else:
                    self.listings = cacheListings
                    self.completed = cacheCompleted
                    return True
        except FileNotFoundError:
            print(f"ERROR: {cacheFilename} was not found")
            return False

    def setTempAsListings(self, tempFilename):
        try: 
            with open(f"lib/{tempFilename}", "r") as f:
                self.listings = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"ERROR: lib/{tempFilename} not found")
        except PermissionError:
            raise PermissionError(f"ERROR: User doesn't have read access to lib/{tempFilename}")

    def cacheListings(self, cacheFilename: str):
        # Cache listings as json file
        cache = {
            "completed": self.completed,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "radiusMiles": self.radiusMiles,
            "listings": self.listings
        }
        try: 
            path = os.path.join("cache/", cacheFilename)
            if not os.path.exists(path):
                Path("cache/").mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=4)
        except FileNotFoundError:
            print(f"ERROR: {cacheFilename} not found")
        except PermissionError:
            print(f"ERROR: User doesn't have write access to the target directory")
        except TypeError:
            print(f"ERROR: Trying to serialize non-serializable type")

    def requestAllListings(self):
        while (self.nRequests < self.requestLimit):
            try: 
                more = self.__requestListings()
                print(f"Gathered {len(self.listings)} listings")
                if not more:
                    break
            except requests.exceptions.HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")  # e.g., 404 Not Found or 500 Server Error
                # TODO implement the different responses to http error codes
                self.apiLimit.failed()
            except requests.exceptions.ConnectionError:
                print("Network error: Failed to connect to the server.")
                self.apiLimit.failed()
            except requests.exceptions.Timeout:
                print("Timeout error: The request took too long.")
                self.apiLimit.failed()
            except requests.exceptions.RequestException as err:
                print(f"A generic requests error occurred: {err}")
                self.apiLimit.failed()
                raise requests.exceptions.RequestException from err
            except ValueError as err:
                raise ValueError from err

    def __requestListings(self):
        self.apiLimit.waitIfTooFast()

        url = f"https://api.rentcast.io/v1/listings/rental/long-term?latitude={self.latitude}&longitude={self.longitude}&radius={self.radiusMiles}&status=Active&limit=500&includeTotalCount=true&offset={len(self.listings)}"
        headers = {
            "accept": "application/json", 
            "X-Api-Key": self.apiKey 
        }
        response = requests.get(url, headers=headers, timeout=60)
        self.apiLimit.justCalled()
        response.raise_for_status()

        data = response.json() 
        if not isinstance(data, list):
            raise ValueError("ERROR: Unexpected Rentcast response format")

        self.listings += response.json()

        # Check if grabbed all, if so, indicated this search is fully completed
        total = int(response.headers.get("X-Total-Count", "0"))
        self.completed = len(self.listings) > total



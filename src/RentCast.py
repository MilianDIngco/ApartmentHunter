import json
from numpy import inf
import requests
import os
from pathlib import Path
from .Models import RateLimiting
from .Models import PropertyType

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
    priceMin: int
    priceMax: int
    propertyTypes: list[PropertyType]

    def __init__(self, apiKey: str, latitude: float, longitude: float, radiusMiles: float, requestLimit: int, priceMin: int = -1, priceMax: int = -1, propertyTypes: list[PropertyType] = []) -> None:
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
        self.priceMin = priceMin
        self.priceMax = priceMax
        self.propertyTypes = propertyTypes
        self.listings = [] # Initialize listings bc if it isn't set from a cache, it's accessed later w/o being init

    def removeUnwantedListings(self):
        checkPropertyTypes = []
        # YES I KNOW THIS IS NOT IDEAL OKAY I AM IN A RUSH TO GO TO THE POOL
        if PropertyType.SingleFamily in self.propertyTypes or self.propertyTypes == []:
            checkPropertyTypes.append("Single Family")
        if PropertyType.Condo in self.propertyTypes or self.propertyTypes == []:
            checkPropertyTypes.append("Condo")
        if PropertyType.Townhouse in self.propertyTypes or self.propertyTypes == []:
            checkPropertyTypes.append("Townhouse")
        if PropertyType.Manufactured in self.propertyTypes or self.propertyTypes == []:
            checkPropertyTypes.append("Manufactured")
        if PropertyType.MultiFamily in self.propertyTypes or self.propertyTypes == []:
            checkPropertyTypes.append("Multi-Family")
        if PropertyType.Apartment in self.propertyTypes or self.propertyTypes == []:
            checkPropertyTypes.append("Apartment")

        pMin = self.priceMin if self.priceMin != -1 else 0
        pMax = self.priceMax if self.priceMax != -1 else inf

        for listing in self.listings[:]:
            propertyType = listing["propertyType"]
            price = listing["price"]
            if ((propertyType in checkPropertyTypes) and  # Valid property type
               price > pMin and price < pMax):          # Valid price range
                continue
            self.listings.remove(listing)

    def getPropertyTypeString(self) -> str:
        if len(self.propertyTypes) == 0:
            return ""
        propertyTypeString = f"propertyType={self.propertyTypes[0]}" 
        if len(self.propertyTypes) == 1:
            return propertyTypeString
        for type in self.propertyTypes[1:]:
            propertyTypeString += f"|{type}"
        return propertyTypeString

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

        # Add preferences to url
        # PRICE RANGES
        urlPriceBase = "&price="
        urlPrice = urlPriceBase
        if (self.priceMin != -1):
            urlPrice += str(self.priceMin) + ":"
        else:
            urlPrice += "*:"
        if (self.priceMax != -1):
            urlPrice += str(self.priceMax)
        else:
            urlPrice += "*"

        if (self.priceMin != 1 or self.priceMax != 1):
            url += urlPrice

        # PROPERTY TYPES
        urlPropertyTypeBase = "&propertyType="
        urlPropertyType = urlPropertyTypeBase
        if len(self.propertyTypes) > 0:
            urlPropertyType += self.propertyTypes[0]
        if len(self.propertyTypes) > 1:
            for propertyType in self.propertyTypes[1:]:
                urlPropertyType += f"|{propertyType}"

        if (urlPropertyType != urlPropertyTypeBase):
            url += urlPropertyType

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


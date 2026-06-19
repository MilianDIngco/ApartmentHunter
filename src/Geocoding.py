import requests
import time

from .Tools import isNum
from .Models import Coordinate

#TODO implement better depth checking
# This class manages 
class Geocoding:
    lastRequest: float
    delay: float
    nSuccess: int
    nRepeatFail: int
    apiKey: str
    disable: bool

    def __init__(self, apiKey: str, disable: bool = False) -> None:
        self.lastRequest = 0
        self.delay = 0.2
        self.nSuccess = 0
        self.nRepeatFail = 0
        self.apiKey = apiKey
        self.disable = disable

    # Given an address, returns a dictionary of form { "lat": xxx, "lon": xxx }. 
    def addressToCoord(self, street, city, state, postalCode, country) -> Coordinate:
        if self.disable:
            return Coordinate(latitude=-1005+self.nRepeatFail, longitude=-1005+self.nRepeatFail)
        # throttle
        elapsed = time.time() - self.lastRequest 
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

        url = f"https://geocode.maps.co/search?street={street}&city={city}&state={state}&postalcode={postalCode}&country={country}&api_key={self.apiKey}"

        try: 
            response = requests.get(url, timeout=60)

            response.raise_for_status()

            self.lastRequest = time.time()
            data = response.json()

            if not data:
                return Coordinate(-1005 + self.nRepeatFail,
                      -1005 + self.nRepeatFail)

            self.nSuccess += 1
            self.nRepeatFail = 0;
            if self.nSuccess > 50:
                self.delay = max(self.delay / 2, 0.2)

            if not isNum(data[0]["lat"]):
                print(f"ERROR: Latitude returned isn't a valid number [{data[0]["lat"]}]")
                self.nRepeatFail += 1
                return Coordinate(latitude=-self.nRepeatFail, longitude=-self.nRepeatFail)
            if not isNum(data[0]["lon"]):
                print(f"ERROR: Longitude returned isn't a valid number [{data[0]["lon"]}]")
                self.nRepeatFail += 1
                return Coordinate(latitude=-1005+self.nRepeatFail, longitude=-1005+self.nRepeatFail)

            return Coordinate(latitude=float(data[0]["lat"]), longitude=float(data[0]["lon"]))
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")  # e.g., 404 Not Found or 500 Server Error

            status = http_err.response.status_code
            if status == 429:
                print("Rate limit hit, backing off")
            elif status in (403, 503):
                print("Geocoding API blocked or unavailable")
            self.nSuccess = 0
            self.delay = max(self.delay + 1, 10)
        except requests.exceptions.ConnectionError:
            print("Network error: Failed to connect to the server.")
        except requests.exceptions.Timeout:
            print("Timeout error: The request took too long.")
        except requests.exceptions.RequestException as err:
            print(f"A generic requests error occurred: {err}")

        self.nRepeatFail += 1
        return Coordinate(latitude=-1005+self.nRepeatFail, longitude=-1005+self.nRepeatFail)


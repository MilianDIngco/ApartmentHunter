import requests
import time

from .Tools import validateCoordinate
from .Models import Coordinate, RateLimiting, QuotaExhaustedError

#TODO implement better depth checking
class Geocoding:
    requestLimit: RateLimiting
    apiKey: str
    MAX_RETRIES: int = 5
    # Makes sense that this class doesn't have an off switch
    # since it doesn't have a request limit

    def __init__(self, apiKey: str) -> None:
        self.requestLimit = RateLimiting(
                    delay=(1 / 5),
                    lastRequest=0,
                    lastFail=0,
                    nFail=0,
                    minDelay=(1 / 5),
                    maxDelay=60,
                    base=2
                )
        self.apiKey = apiKey

    # Given an address, returns a dictionary of form { "lat": xxx, "lon": xxx }. 
    def addressToCoord(self, street, city, state, postalCode, country) -> Coordinate:
        for _ in range(self.MAX_RETRIES):
            try:
                coord = self.requestCoord(street=street, city=city, state=state, postalCode=postalCode, country=country)
                self.requestLimit.succeeded()
                if validateCoordinate(coord):
                    return coord
                else:
                    raise ValueError("Invalid coordinate returned")

            except requests.exceptions.HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")  # e.g., 404 Not Found or 500 Server Error
                self.requestLimit.failed()

                status = http_err.response.status_code if http_err.response else None
                if status == 429:
                    print("Rate limit hit, backing off")
                elif status in (403, 503):
                    raise QuotaExhaustedError("Geocoding API blocked or unavailable")
                elif http_err.response:
                    raise requests.exceptions.RequestException(f"Unhandled HTTP Error: {http_err.response.reason}")
            except requests.exceptions.ConnectionError:
                print("Network error: Failed to connect to the server.")
                self.requestLimit.failed()
            except requests.exceptions.Timeout:
                print("Timeout error: The request took too long.")
                self.requestLimit.failed()
            except requests.exceptions.RequestException as err:
                raise requests.exceptions.RequestException(f"A generic requests error occurred: {err}") from err

        raise QuotaExhaustedError("Geocoding API blocked or unavailable")

    def requestCoord(self, street, city, state, postalCode, country) -> Coordinate:
        self.requestLimit.waitIfTooFast()

        url = f"https://geocode.maps.co/search?street={street}&city={city}&state={state}&postalcode={postalCode}&country={country}&api_key={self.apiKey}"
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        self.requestLimit.justCalled()
        data = response.json()

        if not (data and isinstance(data, list) and data[0].get("lat") and data[0].get("lon")):
            raise ValueError(f"Geocoding returned unexpected response form {data}")

        return Coordinate(latitude=float(data[0]["lat"]), longitude=float(data[0]["lon"]))

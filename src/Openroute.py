import requests 
import time

from .Models import Coordinate, OpenrouteMatrix, OpenrouteSummary, QuotaExhaustedError, RateLimiting

class Openroute:
    failLimit: RateLimiting
    singleLimit: RateLimiting
    matrixLimit: RateLimiting
    apiKey: str
    disableSingle: bool
    disableMatrix: bool
    MAX_RETRIES: int = 5

    def __init__(self, apiKey: str, disable: bool = False) -> None:
        self.failLimit = RateLimiting(
                    minDelay=1,
                    delay=1,
                    maxDelay=60,
                    lastRequest=0,
                    lastFail=0,
                    nFail=0,
                    base=2
                )
        self.singleLimit = RateLimiting(
                    minDelay=(60/40),
                    delay=(60/40),
                    maxDelay=(60/1),
                    lastRequest=0,
                    lastFail=0,
                    nFail=0,
                    base=2
                )
        self.matrixLimit = RateLimiting(
                    minDelay=(60/40),
                    delay=(60/40),
                    maxDelay=(60/1),
                    lastRequest=0,
                    lastFail=0,
                    nFail=0,
                    base=2
                )
        self.apiKey = apiKey
        self.disableSingle = disable
        self.disableMatrix = disable

    def validateCoordinate(self, coord: Coordinate):
        return (
            -90 <= coord.latitude <= 90 and
            -180 <= coord.longitude <= 180
        )

    # Handles choosing matrix route summary vs single route summary, 
    # In the future, it should be able to do batches of locations and their destinations. for now, it'll just do one location to destination
    def getMultipleRouteSummaries(self, locations: list[Coordinate]) -> OpenrouteMatrix | None:
        if self.disableMatrix and self.disableSingle:
            return None

        for location in locations:
            if not self.validateCoordinate(location):
                raise ValueError("Invalid coordinates")

        self.failLimit.reset()
        if not self.disableMatrix:
            for _ in range(self.MAX_RETRIES):
                try:
                    locationsList = [[loc.longitude, loc.latitude] for loc in locations]
                    temp = self.getMatrixRouteSummary(locationsList)
                    self.matrixLimit.lastRequest = time.time()
                    self.matrixLimit.serialSuccessRate() # since succeeded, check if its been long enough

                    # Sanitize null results 
                    result = OpenrouteMatrix(
                        distanceMatrix=[[-1 if dist == None else dist for dist in row] for row in temp.distanceMatrix],
                        durationMatrix=[[-1 if dist == None else dist for dist in row] for row in temp.durationMatrix],
                    )

                    return result

                # TODO 400, 404, 405, 413, 500, 501, 503
                except requests.exceptions.HTTPError as http_err:
                    if http_err.response is not None:
                        match (http_err.response.status_code):
                            case 429:
                                print("Rate limited")
                                self.matrixLimit.lastFail = time.time()
                                self.matrixLimit.exponentialBackoff()
                            case 403:
                                remaining = int(http_err.response.headers.get("X-Ratelimit-Remaining", -1))
                                self.singleLimit.lastFail = time.time()
                                self.singleLimit.exponentialBackoff()
                                if remaining == 0:
                                    print("Quota exhausted")
                                    self.disableMatrix = True
                                else:
                                    print(f"Other error: {http_err.response.reason}")
                                break
                            case _:
                                print(f"Other error: {http_err.response.reason}")
                                self.matrixLimit.lastFail = time.time()
                                self.matrixLimit.exponentialBackoff()
                except requests.exceptions.ConnectionError:
                    print("Network error: Failed to connect to the server.")
                    self.failLimit.lastFail = time.time()
                    self.failLimit.exponentialBackoff()
                except requests.exceptions.Timeout:
                    print("Timeout error: The request took too long.")
                    self.failLimit.lastFail = time.time()
                    self.failLimit.exponentialBackoff()
                except ValueError as e:
                    print(e)
                    raise ValueError from e
                except QuotaExhaustedError as e:
                    print(e)
                    break
                except requests.exceptions.RequestException as err:
                    print(f"A generic requests error occurred: {err}")
                    self.failLimit.lastFail = time.time()
                    self.failLimit.exponentialBackoff()
                self.failLimit.waitIfTooFast()
        
        self.failLimit.reset()

        if not self.disableSingle:
            temp = OpenrouteMatrix(
                distanceMatrix=[[-1.0 for _ in range(len(locations))] for _ in range(len(locations))],
                durationMatrix=[[-1.0 for _ in range(len(locations))] for _ in range(len(locations))]
            )
            for _ in range(self.MAX_RETRIES):
                try:
                    startLoc = locations[0]
                    # Create temporary 2d result matrix
                    for index, dest in enumerate(locations[1:], start=1):
                        # Skip routes that have been successfully found
                        if temp.distanceMatrix[0][index] != -1:
                            continue
                        summary = self.getRouteSummary(
                                startLat=startLoc.latitude,
                                startLon=startLoc.longitude,
                                endLat=dest.latitude,
                                endLon=dest.longitude
                            )
                        self.singleLimit.lastRequest = time.time()
                        temp.distanceMatrix[0][index] = summary.distance
                        temp.durationMatrix[0][index] = summary.duration
                        self.singleLimit.serialSuccessRate()

                    result = temp
                    return result

                # TODO 400, 404, 405, 413, 500, 501, 503
                except requests.exceptions.HTTPError as http_err:
                    if http_err.response is not None:
                        match (http_err.response.status_code):
                            case 429:
                                print("Rate limited")
                                self.singleLimit.lastFail = time.time()
                                self.singleLimit.exponentialBackoff()
                            case 403:
                                remaining = int(http_err.response.headers.get("X-Ratelimit-Remaining", -1))
                                self.singleLimit.lastFail = time.time()
                                self.singleLimit.exponentialBackoff()
                                if remaining == 0:
                                    print("Quota exhausted")
                                    self.disableSingle = True
                                else:
                                    print(f"Other error: {http_err.response.reason}")
                                break
                            case _:
                                print(f"Other error: {http_err.response.reason}")
                                self.singleLimit.lastFail = time.time()
                                self.singleLimit.exponentialBackoff()
                except requests.exceptions.ConnectionError:
                    print("Network error: Failed to connect to the server.")
                    self.failLimit.lastFail = time.time()
                    self.failLimit.exponentialBackoff()
                except requests.exceptions.Timeout:
                    print("Timeout error: The request took too long.")
                    self.failLimit.lastFail = time.time()
                    self.failLimit.exponentialBackoff()
                except ValueError as e:
                    print(e)
                    raise ValueError from e
                except QuotaExhaustedError as e:
                    print(e)
                    break
                except requests.exceptions.RequestException as err:
                    print(f"A generic requests error occurred: {err}")
                    self.failLimit.lastFail = time.time()
                    self.failLimit.exponentialBackoff()

                # If the request fails, wait before making another one
                self.failLimit.waitIfTooFast()

        return None

    def getMatrixRouteSummary(self, locations: list[list[float]]) -> OpenrouteMatrix:
        if self.disableMatrix:
            raise QuotaExhaustedError("OpenRoute Matrix API has been disabled")
        # Handle Matrix API rate limiting
        self.matrixLimit.waitIfTooFast()

        body = {
            "locations": locations,
            "metrics": ["distance", "duration"],
            "units": "mi"
        }
        response = requests.post(
            "https://api.heigit.org/openrouteservice/v2/matrix/driving-car",
            json=body,
            headers={
                "Accept": "application/json, application/geo+json, application/gpx+xml, img/png; charset=utf-8",
                "Authorization": self.apiKey,
                "Content-Type": "application/json; charset=utf-8"
            },
            timeout=60
        )

        response.raise_for_status()
        data = response.json()
        try:
            return OpenrouteMatrix(
                distanceMatrix=data["distances"],
                durationMatrix=data["durations"]
            )
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(f"Unexpected response structure from openroute service: {data}") from e

    def getRouteSummary(self, startLat: float, startLon: float, endLat: float, endLon: float) -> OpenrouteSummary:
        if self.disableSingle:
            raise QuotaExhaustedError("OpenRoute Single API has been disabled")
        # Handle Single API rate limiting
        self.singleLimit.waitIfTooFast()
        
        url = f"https://api.heigit.org/openrouteservice/v2/directions/driving-car?api_key={self.apiKey}&start={startLon},{startLat}&end={endLon},{endLat}"
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()
        try:
            summary = data["features"][0]["properties"]["summary"]
            return OpenrouteSummary(
                distance=summary["distance"], 
                duration=summary["duration"]
            )
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(f"Unexpected response structure from openroute service: {data}") from e

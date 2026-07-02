import requests 

from .Tools import validateCoordinate
from .Models import Coordinate, OpenrouteMatrix, OpenrouteSummary, QuotaExhaustedError, RateLimiting

# Makes sense that this DOES have disabling built into
# the class since it has a daily quota
class Openroute:
    singleLimit: RateLimiting
    matrixLimit: RateLimiting
    apiKey: str
    disableSingle: bool
    disableMatrix: bool
    MAX_RETRIES: int = 5

    def __init__(self, apiKey: str, disable: bool = False) -> None:
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

    # Handles choosing matrix route summary vs single route summary, 
    # In the future, it should be able to do batches of locations and their destinations. for now, it'll just do one location to destination
    def getMultipleRouteSummaries(self, locations: list[Coordinate]) -> OpenrouteMatrix:
        if self.disableMatrix and self.disableSingle:
            return OpenrouteMatrix.invalidMatrix(len(locations))

        # Replace invalid locations with root location
        for index, location in enumerate(locations):
            if not validateCoordinate(location):
                locations[index] = locations[0]

        if not self.disableMatrix:
            for _ in range(self.MAX_RETRIES):
                try:
                    locationsList = [[loc.longitude, loc.latitude] for loc in locations]
                    temp = self.getMatrixRouteSummary(locationsList)
                    self.matrixLimit.succeeded() # since succeeded, check if its been long enough

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
                                self.matrixLimit.failed()
                            case 403:
                                remaining = int(http_err.response.headers.get("X-Ratelimit-Remaining", -1))
                                self.matrixLimit.failed()
                                self.disableMatrix = True
                                if remaining == 0:
                                    print("Quota exhausted")
                                else:
                                    print(f"Other error: {http_err.response.reason}")
                                break
                            case _:
                                print(f"Other error: {http_err.response.reason}")
                                self.matrixLimit.failed()
                except requests.exceptions.ConnectionError:
                    print("Network error: Failed to connect to the server.")
                    self.matrixLimit.failed()
                except requests.exceptions.Timeout:
                    print("Timeout error: The request took too long.")
                    self.matrixLimit.failed()
                except ValueError as e:
                    raise ValueError("Openroute Value Error: ") from e
                except QuotaExhaustedError as e:
                    print(e)
                    self.disableMatrix = True
                    break
                except requests.exceptions.RequestException as err:
                    print(f"A generic requests error occurred: {err}")
                    self.matrixLimit.failed()
                    raise requests.exceptions.RequestException from err

        if not self.disableSingle:
            notFound = 0
            found = 0
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
                        try:
                            summary = self.getRouteSummary(
                                    startLat=startLoc.latitude,
                                    startLon=startLoc.longitude,
                                    endLat=dest.latitude,
                                    endLon=dest.longitude
                                )
                            found += 1
                            self.singleLimit.succeeded()
                            temp.distanceMatrix[0][index] = summary.distance
                            temp.durationMatrix[0][index] = summary.duration
                        except requests.exceptions.HTTPError as http_err:
                            if http_err.response is not None:
                                match (http_err.response.status_code):
                                    case 404:
                                        body = http_err.response.json()
                                        errorCode = body.get("error", {}).get("code")
                                        if errorCode == 2009 or errorCode == 2010:
                                            print("No route found between two points, skipping")
                                            notFound += 1
                                            continue
                                        else:
                                            print(f"Server error: {body.get("error", {}).get("message")}")
                                            self.singleLimit.failed()
                            raise

                    result = temp
                    return result

                # TODO 400, 404, 405, 413, 500, 501, 503
                except requests.exceptions.HTTPError as http_err:
                    if http_err.response is not None:
                        match (http_err.response.status_code):
                            case 429:
                                print("Rate limited")
                                self.singleLimit.failed()
                            case 403:
                                remaining = int(http_err.response.headers.get("X-Ratelimit-Remaining", -1))
                                self.singleLimit.failed()
                                self.disableSingle = True
                                if remaining == 0:
                                    print("Quota exhausted")
                                else:
                                    print(f"Other error: {http_err.response.reason} {http_err.response.json().get("error")}")
                                break
                            case _:
                                print(f"Other error: {http_err.response.reason} {http_err.response.status_code} {http_err.response.json().get("error")}")
                                self.singleLimit.failed()
                except requests.exceptions.ConnectionError:
                    print("Network error: Failed to connect to the server.")
                    self.singleLimit.failed()
                except requests.exceptions.Timeout:
                    print("Timeout error: The request took too long.")
                    self.singleLimit.failed()
                except ValueError as e:
                    print(e)
                    raise ValueError from e
                except QuotaExhaustedError as e:
                    print(e)
                    self.disableSingle = True
                    break
                except requests.exceptions.RequestException as err:
                    print(f"A generic requests error occurred: {err}")
                    self.singleLimit.failed()
                    raise requests.exceptions.RequestException from err
            if (notFound + found) == len(locations):
                print("Apartment could not find any POI routes")
                return OpenrouteMatrix.invalidMatrix(len(locations))


        # If i reach this point, I probably can't even call openroute api and need to break and cache the results
        raise QuotaExhaustedError("OpenRoute API has been disabled")

    def getMatrixRouteSummary(self, locations: list[list[float]]) -> OpenrouteMatrix:
        if self.disableMatrix:
            raise QuotaExhaustedError("OpenRoute Matrix API has been disabled")
        # Handle Matrix API rate limiting
        self.matrixLimit.waitIfTooFast()

        body = {
            "locations": locations,
            "metrics": ["distance", "duration"],
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

        self.matrixLimit.justCalled()

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
        self.singleLimit.justCalled()
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

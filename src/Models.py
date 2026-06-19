from dataclasses import dataclass
import time

class QuotaExhaustedError(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
@dataclass 
class OpenrouteSummary:
    distance: float = -1
    duration: float = -1

@dataclass
class OpenrouteMatrix:
    distanceMatrix: list[list[float]]
    durationMatrix: list[list[float]]

@dataclass
class RateLimiting:
    delay: float # (sec) current delay 
    lastRequest: float # timestamp of last request
    lastFail: float # timestamp of last failure
    nFail: int # number of times API returned a bad response
    minDelay: float # (sec) minimum delay that the API allows
    maxDelay: float # (sec) maximum delay user wants
    base: int # used to determine how quickly the rate will back off

    def reset(self):
        self.delay = self.minDelay
        self.lastRequest = 0
        self.lastFail = 0
        self.nFail = 0

    # utility for APIs to wait if current request is too fast
    def waitIfTooFast(self):
        if self.tooFast():
            self.wait()

    # Checks if the attempted request is too fast
    def tooFast(self) -> bool:
        elapsed = time.time() - self.lastRequest
        return elapsed < self.delay

    # Waits until the defined delay has passed
    def wait(self):
        elapsed = time.time() - self.lastRequest
        remaining = self.delay - elapsed + 0.2
        try:
            time.sleep(remaining)
        except ValueError:
            print("WARNING: No need to wait, time elapsed > set delay")

    # Decreases delay additively when success is sustained
    def serialSuccessRate(self):
        sustainedSuccess = time.time() - self.lastFail
        if sustainedSuccess > 60:
            self.delay = max(self.minDelay, self.delay - 1)

    # Increases delay exponentially when failing
    def exponentialBackoff(self):
        self.delay = min(self.base ** self.nFail, self.maxDelay)


@dataclass
class Coordinate:
    latitude: float
    longitude: float

@dataclass
class POI:
    location: Coordinate
    commute: OpenrouteSummary

@dataclass
class Address:
    street: str
    city: str
    state: str
    postal: str

@dataclass
class ListingInfo:
    location: Coordinate
    address: str
    listedPrice: str
    workCommute: OpenrouteSummary | str
    supermarketCommute: OpenrouteSummary | str
    libraryCommute: OpenrouteSummary | str
    parkCommute: OpenrouteSummary | str
    bedrooms: int
    bathrooms: int

@dataclass
class ListingExcel:
    address: str
    location: str
    listedPrice: str
    workCommuteDuration: float | str
    workCommuteDistance: float | str
    supermarketCommuteDuration: float  | str
    supermarketCommuteDistance: float | str
    libraryCommuteDuration: float | str
    libraryCommuteDistance: float | str
    parkCommuteDuration: float | str
    parkCommuteDistance: float | str
    bedrooms: int
    bathrooms: int

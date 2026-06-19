import os
import json
import argparse
from dotenv import load_dotenv, find_dotenv
import usaddress
import re
import pandas as pd
from dataclasses import asdict
from src.Models import Coordinate, ListingExcel, OpenrouteMatrix
from src.Models import OpenrouteSummary
from src.Models import POI
from src.RentCast import RentCast
from src.Openroute import Openroute
from src.Geocoding import Geocoding
from src.Geoapify import Geoapify
from src.Tools import isNum, validXLSXFilename, parseAddressString

searchParamExample = {
    "centerAddress": None,
    "workAddress": None,
    "searchRadiusMiles": 0
}

useTemp = False
disableOpenroute = False
rentcastCacheOnly = True
rentcastLimit = 450

args = None

def main():
    # Grab command line arguments
    parser = argparse.ArgumentParser(description="A commandline tool to help you find apartments and their distances to points of interest")

    parser.add_argument("-t", "--useTemp", help="Uses the JSON file filled with example listings from RentCast instead of calling the API. Takes a filename to the JSON file. File should live in the lib/ directory, and filename should end in .json", type=str)
    parser.add_argument("-O", "--disableOpenroute", action="store_true", help="Disables the openroute request API")
    parser.add_argument("-c", "--rentcastCacheOnly", action="store_true", help="If a cache filename is provided and valid, only use the cached listings and do not call the RentCast API.")
    parser.add_argument("-C", "--rentcastCacheFilename", type=str, help="Sets the filename to the cached listing .json file, that the program will use instead of or in addition to the listings provided by the rentcast API")
    parser.add_argument("-S", "--searchParameterFilename", type=str, help=f"""Sets the filename to the search parameter json file. This file should follow the following form: 
    {searchParamExample}
""")
    parser.add_argument("-L", "--rentcastRequestLimit", default=0, type=int, help="Since Rentcast has the lowest monthly limit, this option is available to set the number of maximum allowed requests. If you are above the quota, and want to pay, setting this above zero will allow you to do that, but it is 20 cents per request since you are on the free plan")
    args = parser.parse_args()

    print(f"useTemp: {args.useTemp}")
    print(f"disableOpenroute: {args.disableOpenroute}")
    print(f"rentcastCacheOnly: {args.rentcastCacheOnly}")
    print(f"rentcastCacheFilename: {args.rentcastCacheFilename}")
    print(f"searchParameterFilename: {args.searchParameterFilename}")
    print(f"rentcastRequestLimit: {args.rentcastRequestLimit}")

    # TODO im sure theres better ways to handle arg priority but... buh.. buss
    if args.rentcastCacheOnly:
        args.rentcastRequestLimit = 0

    # Get centering and work address, and searchRadius
    searchParams = None
    if args.searchParameterFilename:
        try:
            with open(args.searchParameterFilename, "r") as f:
                searchParams = json.load(f)

                # Checking form
                if not searchParamExample.keys() <= searchParams.keys():
                    missing = searchParamExample.keys() - searchParams.keys()
                    print(f"ERROR: missing fields in search params: {missing}")
                    searchParams = None
                else:
                    # On success, transform address strings into parsedAddresses
                    centerAddress = parseAddressString(searchParams["centerAddress"])
                    workAddress = parseAddressString(searchParams["workAddress"])
                    failed = False
                    if centerAddress is None:
                        print(f"ERROR: {searchParams["centerAddress"]} is not a valid center address")
                        failed = True
                    if workAddress is None:
                        print(f"ERROR: {searchParams["workAddress"]} is not a valid work address")
                        failed = True

                    if failed:
                        searchParams = None
                    else:
                        searchParams["centerAddress"] = centerAddress
                        searchParams["workAddress"] = workAddress
        except FileNotFoundError:
            print(f"ERROR: {args.searchParameterFilename} not found")
            
    # Ask for user input to get search parameters
    if searchParams is None:
        searchParams = grabSearchParamInput()

    # Grab API keys
    load_dotenv(find_dotenv())
    rentcast_APIKEY = os.getenv("RENTCAST_APIKEY")
    geocoding_APIKEY = os.getenv("GEOCODING_APIKEY")
    openroute_APIKEY = os.getenv("OPENROUTE_APIKEY")
    geoapify_APIKEY = os.getenv("GEOAPIFY_APIKEY")

    if (rentcast_APIKEY is None or
        geocoding_APIKEY is None or
        openroute_APIKEY is None or
        geoapify_APIKEY is None):
        print("ERROR: Failed to get an APIKEY, check your .env file")
        exit(1)

    # Grab coordinates for center and work
    geocoding = Geocoding(apiKey=geocoding_APIKEY)

    while (centerCoord := geocoding.addressToCoord(
            street=searchParams["centerAddress"].street, 
            city=searchParams["centerAddress"].city, 
            state=searchParams["centerAddress"].state, 
            postalCode=searchParams["centerAddress"].postal, 
            country="US")
           ).latitude < -1000:
        print(f"Trying to grab center coordinate again, attempts left: {-centerCoord.latitude}")

    print(f"Center coordinate: lat={centerCoord.latitude}, lon={centerCoord.longitude}")

    while (workCoord := geocoding.addressToCoord(
            street=searchParams["workAddress"].street, 
            city=searchParams["workAddress"].city, 
            state=searchParams["workAddress"].state, 
            postalCode=searchParams["workAddress"].postal, 
            country="US")
           ).latitude < -1000: 
        print(f"Trying to grab work coordinate again, attempts left: {-workCoord.latitude}")

    print(f"Work coordinate: lat={workCoord.latitude}, lon={workCoord.longitude}")

    # Grab listings w/ option
    rentcast = RentCast(apiKey=rentcast_APIKEY,
                        latitude=centerCoord.latitude,
                        longitude=centerCoord.longitude,
                        radiusMiles=searchParams["searchRadiusMiles"],
                        requestLimit=args.rentcastRequestLimit)

    print(f"Starting search on [{searchParams["centerAddress"]}], with a search radius of {searchParams["searchRadiusMiles"]} miles, and commute address at [{searchParams["workAddress"]}]")

    if os.path.isfile(f"lib/{args.useTemp}"): 
        rentcast.setTempAsListings(args.useTemp)
    elif os.path.isfile(args.rentcastCacheFilename): 
        rentcast.loadCache(args.rentcastCacheFilename)

    if (not args.rentcastCacheOnly) and (args.useTemp is None): 
        rentcast.requestAllListings()
    
    # Initialize API classes
    openroute = Openroute(apiKey=openroute_APIKEY, disable=args.disableOpenroute)
    geoapify = Geoapify(apiKey=geoapify_APIKEY)

    # Iterate over all listings
    listingsDict = []
    nListings = len(rentcast.listings)
    nCompleted = 0

    for listing in rentcast.listings:
        # ================================SIMPLE INCLUDED DATA=================================
        print("Getting listing info: ")
        listingLat = listing.get("latitude", "-1")
        listingLon = listing.get("longitude", "-1")
        if not isNum(listingLat):
            listingLat = -1
        if not isNum(listingLon):
            listingLon = -1
        listingCoord = Coordinate(latitude=float(listingLat), longitude=float(listingLon))
        print(f"Coordinate: {listingCoord}")
        listingAddr = listing.get("formattedAddress", "No address provided")
        print(f"Address: {listingAddr}")
        listingPrice = listing.get("price", "No price provided")
        print(f"Price: {listingPrice}")
        listingBedrooms = listing.get("bedrooms", "-1")
        print(f"Bedrooms: {listingBedrooms}")
        listingBathrooms = listing.get("bathrooms", "-1")
        print(f"Bathrooms: {listingBathrooms}")
        # ===============================OPENROUTE SERVICE===================================
        pois = geoapify.findPOIs(
            latitude=listingLat, 
            longitude=listingLon, 
            radiusMiles=searchParams["searchRadiusMiles"]
        )
        supermarket = pois.get("Supermarket")
        library = pois.get("Library")
        park = pois.get("Park")
        locations = [
            listingCoord,
            workCoord,
            supermarket if supermarket is not None else listingCoord,
            library if library is not None else listingCoord,
            park if park is not None else listingCoord
        ]

        summary = openroute.getMatrixRouteSummary(locations)

        if summary is None or summary.distanceMatrix is None or summary.durationMatrix is None:
            print(f"ERROR: Failed to get matrix summary for {listingAddr}")
            summary = OpenrouteMatrix(
                distanceMatrix=[[-1 for _ in range(6)] for _ in range(6)],
                durationMatrix=[[-1 for _ in range(6)] for _ in range(6)]
            )

        listingWork = OpenrouteSummary(
                    duration=summary.durationMatrix[0][1],
                    distance=summary.distanceMatrix[0][1]
                )
        listingSupermarket = OpenrouteSummary(
                    duration=summary.durationMatrix[0][2],
                    distance=summary.distanceMatrix[0][2]
                )
        listingLibrary = OpenrouteSummary(
                    duration=summary.durationMatrix[0][3],
                    distance=summary.distanceMatrix[0][3]
                )
        listingPark = OpenrouteSummary(
                    duration=summary.durationMatrix[0][4],
                    distance=summary.distanceMatrix[0][4]
                )
        print(f"Work commute: {listingWork}")
        print(f"Supermarket commute: {listingSupermarket}")
        print(f"Library commute: {listingLibrary}")
        print(f"Park commute: {listingPark}")
        
        info = ListingExcel(
                    address=listingAddr,
                    location=f"{listingCoord.latitude}, {listingCoord.longitude}",
                    listedPrice=listingPrice,
                    workCommuteDuration=listingWork.duration / 60,
                    workCommuteDistance=listingWork.distance / 1609,
                    supermarketCommuteDuration=listingSupermarket.duration / 60,
                    supermarketCommuteDistance=listingSupermarket.distance / 1609,
                    libraryCommuteDuration=listingLibrary.duration / 60,
                    libraryCommuteDistance=listingLibrary.distance / 1609,
                    parkCommuteDuration=listingPark.duration / 60,
                    parkCommuteDistance=listingPark.distance / 1609,
                    bedrooms=listingBedrooms,
                    bathrooms=listingBathrooms
                )

        listingsDict.append(asdict(info))

        nCompleted += 1
        print(f"Completion: {100 * nCompleted / nListings}%")

    # Save as excel spreadsheet
    df = pd.DataFrame(listingsDict)
    df.columns=["Address", "Coord", "Price", "Work Dist(mi)", "Work Dur(min)", "Supermarket Dist(mi)", "Supermarket Dur(min)", "Library Dist(mi)", "Library Dur(min)", "Park Dist(mi)", "Park Dur(min)", "bedrooms", "bathrooms"]

    while not validXLSXFilename(filename := input("Enter the filename you would like to save the data into (include the file extension .xlsx): ")):
        print("Enter a valid filename")

    df.to_excel(filename, index=False, float_format="%.2f")

def grabSearchParamInput() -> dict:
    searchParams = searchParamExample.copy()

    while True:
        centerAddress = input("Enter an address to center your search around (# Street, City, State, Zip code): ")

        parsedCenterAddress = parseAddressString(centerAddress)

        if parsedCenterAddress is None:
            print("Please enter a valid address")
            continue

        print(parsedCenterAddress)

        if input("Is this correct? (Y/n): ")[0].lower() != 'y':
            continue
        else:
            searchParams["centerAddress"] = parsedCenterAddress 
            break

    # Take search radius
    while True:
        searchRadius = input("Enter the search radius in miles: ")
        if not isNum(searchRadius):
            print("Enter a valid number for the search in miles")
            continue
        searchRadius = float(searchRadius)
        if searchRadius > 100:
            print("The maximum search radius is 100 miles.")
            continue
        searchParams["searchRadiusMiles"] = searchRadius
        break
        
    # Take work address
    while True:
        workAddress = input("Enter your work address (# Street, City, State, Zip code): ")

        parsedWorkAddress = parseAddressString(workAddress)

        if parsedWorkAddress is None:
            print("Please enter a valid address")
            continue

        print(parsedWorkAddress)

        if input("Is this correct? (Y/n): ")[0].lower() != 'y':
            continue
        else:
            searchParams["workAddress"] = parsedWorkAddress
            break

    return searchParams


if __name__ == "__main__":
    main()

import os
import json
import argparse
from typing import List
import requests
from dotenv import load_dotenv, find_dotenv
import pandas as pd
from pathlib import Path
from dataclasses import asdict
from src.Models import Coordinate, ListingExcel, QuotaExhaustedError
from src.Models import OpenrouteSummary
from src.Models import PropertyType
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

optionalSearchParams = {
    "priceMinimum": 0,
    "priceMaximum": 0,
    "propertyTypes": None
}

propertyTypeNames = {
    "singlefamily" : PropertyType.SingleFamily,
    "condo" : PropertyType.Condo,
    "townhouse" : PropertyType.Townhouse,
    "manufactured": PropertyType.Manufactured,
    "multifamily": PropertyType.MultiFamily,
    "apartment": PropertyType.Apartment
}

useTemp = False
disableOpenroute = False
rentcastCacheOnly = True
rentcastLimit = 450

# ADD CATEGORIES FROM https://apidocs.geoapify.com/docs/places/#categories
# but be aware, for each category, it requires another API request to OpenRoute
# which has a daily quota. 
poiCategories = [
    "leisure.park",
    "commercial.supermarket",
    "education.library"
]

def main():
    args = setCommandLineArguments()

    # Get centering and work address, and searchRadius
    searchParams = None
    if args.searchParameterFilename:
        try:
            with open(args.searchParameterFilename, "r") as f:
                searchParams = json.load(f)

                # Checking form for bare minimum keys
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
                    
                        # Check for optional keys
                        listingTypes = []
                        if "propertyTypes" in searchParams.keys():
                            listingTypes = [propertyTypeNames[lt] for lt in searchParams["listingType"] if lt in propertyTypeNames.keys()]
                        searchParams["propertyTypes"] = listingTypes

                        if "priceMinimum" in searchParams.keys():
                            priceMinimum = searchParams["priceMinimum"]
                            if isNum(priceMinimum) and priceMinimum > 0:
                                searchParams["priceMinimum"] = priceMinimum
                            else:
                                searchParams["priceMinimum"] = -1
                        else:
                            searchParams["priceMinimum"] = -1

                        if "priceMaximum" in searchParams.keys():
                            priceMaximum = searchParams["priceMaximum"]
                            if isNum(priceMaximum) and priceMaximum > searchParams["priceMinimum"]:
                                searchParams["priceMaximum"] = priceMaximum
                            else:
                                searchParams["priceMaximum"] = -1
                        else:
                            searchParams["priceMaximum"] = -1

        except FileNotFoundError:
            print(f"ERROR: {args.searchParameterFilename} not found")
            
    # Ask for user input to get search parameters
    if searchParams is None:
        searchParams, searchParamsFilename = grabAndSaveSearchParamInput()
    else:
        # if didn't have to, it means it got the search params from args
        searchParamsFilename = args.searchParameterFilename

    # Ask for excel filename output if not provided
    outputExcelFilename = args.outputExcelFilename if args.outputExcelFilename else ""
    if args.outputExcelFilename and validXLSXFilename(filename=args.outputExcelFilename):
        outputExcelFilename = args.outputExcelFilename
    else:
        while not validXLSXFilename(outputExcelFilename := input("Enter the filename you would like to save the data into (include the file extension .xlsx): ")):
            print("Enter a valid filename")

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

    centerCoord = geocoding.addressToCoord(
            street=searchParams["centerAddress"].street, 
            city=searchParams["centerAddress"].city, 
            state=searchParams["centerAddress"].state, 
            postalCode=searchParams["centerAddress"].postal, 
            country="US")

    print(f"Center coordinate: lat={centerCoord.latitude}, lon={centerCoord.longitude}")

    workCoord = geocoding.addressToCoord(
            street=searchParams["workAddress"].street, 
            city=searchParams["workAddress"].city, 
            state=searchParams["workAddress"].state, 
            postalCode=searchParams["workAddress"].postal, 
            country="US")

    print(f"Work coordinate: lat={workCoord.latitude}, lon={workCoord.longitude}")

    # Grab listings w/ option
    rentcast = RentCast(apiKey=rentcast_APIKEY,
                        latitude=centerCoord.latitude,
                        longitude=centerCoord.longitude,
                        radiusMiles=searchParams["searchRadiusMiles"],
                        requestLimit=args.rentcastRequestLimit,
                        priceMin=searchParams["priceMinimum"],
                        priceMax=searchParams["priceMaximum"],
                        propertyTypes=searchParams["propertyTypes"]
                        )
    
    print(f"Starting search on [{searchParams["centerAddress"]}], with a search radius of {searchParams["searchRadiusMiles"]} miles, and commute address at [{searchParams["workAddress"]}]")
    print(f"Will be able to run {500 + 2000 / len(poiCategories)} requests today, assuming OpenRoute quota has fully reset")

    if not os.path.exists("cache/"):
        Path("cache/").mkdir(parents=True, exist_ok=True)

    if args.useTemp and os.path.isfile(f"lib/{args.useTemp}"): 
        rentcast.setTempAsListings(args.useTemp)
    elif args.rentcastCacheFilename and os.path.isfile(f"cache/{args.rentcastCacheFilename}"): 
        rentcast.loadCache(args.rentcastCacheFilename)

    if (not args.rentcastCacheOnly) and (args.useTemp is None): 
        try: 
            rentcast.requestAllListings()
            # Cache listings if new listings were grabbed
            rentcast.cacheListings(cacheFilename=args.rentcastCacheFilename)
        except ValueError as err:
            print(f"ERROR: ")
        except requests.exceptions.RequestException as err:
            print(f"ERROR: ")
        except QuotaExhaustedError as err:
            print(f"ERROR: ")

    # Check validity of listings, if invalid, quit program
    if len(rentcast.listings) == 0:
        print("ERROR: No listings found. Check if RentCast is available")
        exit(0)

    rentcast.removeUnwantedListings()
    
    # Grab processed cache
    processedCache = None
    processedCachePath = os.path.join("cache/", args.processedCacheFilename)
    if args.processedCacheFilename and args.rentcastCacheFilename and os.path.exists(processedCachePath):
        with open(processedCachePath, "r") as f:
            processedCache = json.load(f)

    # Initialize API classes
    openroute = Openroute(apiKey=openroute_APIKEY, disable=args.disableOpenroute)
    geoapify = Geoapify(apiKey=geoapify_APIKEY)

    # Iterate over all listings
    listingsDict = []
    nListings = len(rentcast.listings)
    nCompleted = 0

    for index, listing in enumerate(rentcast.listings):
        print(f"Completion: {100 * len(listingsDict) / nListings}%")
        print(f"{len(listingsDict)} / {nListings}")
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
        
        # ===============================Check for duplicates===================================

        if processedCache and index < len(processedCache):
            processedListing = processedCache[index]
            
            if (processedListing["address"] == listingAddr and
                processedListing["location"] == f"{listingCoord.latitude}, {listingCoord.longitude}" and
                processedListing["bedrooms"] == listingBedrooms and
                processedListing["bathrooms"] == listingBathrooms):
                listingsDict.append(processedListing)
                continue
            
        # ===============================GEOAPIFY POI SERVICE===================================
        pois = geoapify.findPOIs(
            latitude=listingCoord.latitude, 
            longitude=listingCoord.longitude, 
            radiusMiles=searchParams["searchRadiusMiles"],
            poiCategories=poiCategories
        )
        locations = [
            listingCoord,
            workCoord
        ]
        for name in poiCategories:
            coord = pois.get(name)
            locations.append(coord if coord else listingCoord) # Use listing coord if no POI found -> res = 0

        # ===============================OPENROUTE SERVICE===================================
        try:
            print("Finding Routes")
            summary = openroute.getMultipleRouteSummaries(locations)
            workSummary = OpenrouteSummary(
                        duration=summary.durationMatrix[0][1],
                        distance=summary.distanceMatrix[0][1]
                    )
            print(f"Work commute: {workSummary}")
            poiSummaries = {}
            for index, name in enumerate(poiCategories):
                poiSummaries[name] = OpenrouteSummary(
                            duration=summary.durationMatrix[0][index + 2],
                            distance=summary.distanceMatrix[0][index + 2]
                        )
                print(f"{name} commute: {poiSummaries[name]}")
            
            info = ListingExcel(
                        address=listingAddr,
                        location=f"{listingCoord.latitude}, {listingCoord.longitude}",
                        listedPrice=listingPrice,
                        bedrooms=listingBedrooms,
                        bathrooms=listingBathrooms,
                        workCommuteDuration=workSummary.duration / 60,
                        workCommuteDistance=workSummary.distance / 1609
                    )

            # Convert to dictionary and add summaries dynamically
            infoDict = asdict(info)
            for key, value in poiSummaries.items():
                infoDict[f"{key}CommuteDuration"]=value.duration / 60
                infoDict[f"{key}CommuteDistance"]=value.distance / 1609

            listingsDict.append(infoDict)

            nCompleted += 1
        except ValueError as err:
            print(f"ERROR: Unexpected value format from route summary: {err.args}")
            if nCompleted > 0:
                cacheProcessed(processed=listingsDict, 
                               processedCacheFilename=args.processedCacheFilename
                               )
                print(f"""
                Once the quota has reset, run 
                    `python3 main.py {"-c " if rentcast.completed else ""}-C {args.rentcastCacheFilename} -S {searchParamsFilename} -P {args.processedCacheFilename}{" -E " if outputExcelFilename != "" else ""}{outputExcelFilename} [-L <rentcastLimit>]`
                Set rentcastLimit if you're broke and the quota hasn't reset and can't pay for the reqs
                """)
                columns=["Address", "Coord", "Price", "Bedrooms", "Bathrooms", "Work Dur(min)", "Work Dist(mi)"]
                generatePOIColumnNames(columns, poiCategories)
                saveExcel(listingsDict, columns, outputExcelFilename)
            exit(1)
        except requests.exceptions.RequestException as err:
            print(f"ERROR: Unhandled error from route summary {err}")
            if nCompleted > 0:
                cacheProcessed(processed=listingsDict, 
                               processedCacheFilename=args.processedCacheFilename
                               )
                print(f"""
                Once the quota has reset, run 
                    `python3 main.py {"-c " if rentcast.completed else ""}-C {args.rentcastCacheFilename} -S {searchParamsFilename} -P {args.processedCacheFilename}{" -E " if outputExcelFilename != "" else ""}{outputExcelFilename} [-L <rentcastLimit>]`
                Set rentcastLimit if you're broke and the quota hasn't reset and can't pay for the reqs
                """)
                columns=["Address", "Coord", "Price", "Bedrooms", "Bathrooms", "Work Dur(min)", "Work Dist(mi)"]
                generatePOIColumnNames(columns, poiCategories)
                saveExcel(listingsDict, columns, outputExcelFilename)
            exit(1)
        except QuotaExhaustedError as err:
            print(f"ERROR: Quota {err}")
            if nCompleted > 0:
                cacheProcessed(processed=listingsDict, 
                               processedCacheFilename=args.processedCacheFilename
                               )
                print(f"""
                Once the quota has reset, run 
                    `python3 main.py {"-c " if rentcast.completed else ""}-C {args.rentcastCacheFilename} -S {searchParamsFilename} -P {args.processedCacheFilename}{" -E " if outputExcelFilename != "" else ""}{outputExcelFilename} [-L <rentcastLimit>]`
                Set rentcastLimit if you're broke and the quota hasn't reset and can't pay for the reqs
                """)
                columns=["Address", "Coord", "Price", "Bedrooms", "Bathrooms", "Work Dur(min)", "Work Dist(mi)"]
                generatePOIColumnNames(columns, poiCategories)
                saveExcel(listingsDict, columns, outputExcelFilename)
            exit(1)


    # Cache in case it fails
    cacheProcessed(processed=listingsDict, 
                   processedCacheFilename=args.processedCacheFilename
                   )
    # Save as excel spreadsheet
    columns=["Address", "Coord", "Price", "Bedrooms", "Bathrooms", "Work Dur(min)", "Work Dist(mi)"]
    generatePOIColumnNames(columns, poiCategories)
    saveExcel(listingsDict, columns, outputExcelFilename)
    print(f"Successfully saved listings to {outputExcelFilename}")

def setCommandLineArguments():
    # Grab command line arguments
    parser = argparse.ArgumentParser(description="A commandline tool to help you find apartments and their distances to points of interest")

    parser.add_argument("-t", "--useTemp", help="Uses the JSON file filled with example listings from RentCast instead of calling the API. Takes a filename to the JSON file. File should live in the lib/ directory, and filename should end in .json", type=str)
    parser.add_argument("-O", "--disableOpenroute", action="store_true", help="Disables the openroute request API")
    parser.add_argument("-c", "--rentcastCacheOnly", action="store_true", help="If a cache filename is provided and valid, only use the cached listings and do not call the RentCast API.")
    parser.add_argument("-C", "--rentcastCacheFilename", type=str, help="Sets the filename to the cached listing .json file, that the program will use instead of or in addition to the listings provided by the rentcast API")
    parser.add_argument("-S", "--searchParameterFilename", type=str, help=f"""Sets the filename to the search parameter json file. This file should follow the following form: 
    {searchParamExample}
""")
    parser.add_argument("-P", "--processedCacheFilename", default="processed.json", type=str, help="Sets the filename to the cached processed listing .json file. These will hold the listings that have been processed, and when running again, will use to skip")
    parser.add_argument("-E", "--outputExcelFilename", type=str, help="Sets the filename the output excel file will be written to")
    parser.add_argument("-L", "--rentcastRequestLimit", default=0, type=int, help="Since Rentcast has the lowest monthly limit, this option is available to set the number of maximum allowed requests. If you are above the quota, and want to pay, setting this above zero will allow you to do that, but it is 20 cents per request since you are on the free plan")
    args = parser.parse_args()

    print(f"useTemp: {args.useTemp}")
    print(f"disableOpenroute: {args.disableOpenroute}")
    print(f"rentcastCacheOnly: {args.rentcastCacheOnly}")
    print(f"rentcastCacheFilename: {args.rentcastCacheFilename}")
    print(f"searchParameterFilename: {args.searchParameterFilename}")
    print(f"processedCacheFilename: {args.processedCacheFilename}")
    print(f"rentcastRequestLimit: {args.rentcastRequestLimit}")

    # TODO im sure theres better ways to handle arg priority but... buh.. buss
    if args.rentcastCacheOnly or args.useTemp:
        args.rentcastRequestLimit = 0

    return args

def grabAndSaveSearchParamInput() -> tuple[dict, str]:
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
#optionalSearchParams = {
#    "priceMinimum": 0,
#   "priceMaximum": 0,
#   "propertyTypes": None
#}

    # Take priceMinimum
    while True:
        priceMinimum = -1
        priceMinimumInput = input("Enter the minimum desired price (Press enter to set no minimum value): ")
        if priceMinimumInput.strip() != "" and isNum(priceMinimumInput):
            priceMinimum = float(priceMinimumInput)

        if input(f"Is this correct? (Y/n): {priceMinimum if priceMinimum != -1 else "Use no minimum value"}")[0].lower() != 'y':
            continue
        else:
            searchParams["priceMinimum"] = priceMinimum
            break

    while True:
        priceMaximum = -1
        priceMaximumInput = input("Enter the minimum desired price (Press enter to set no minimum value): ")
        if priceMaximumInput.strip() != "" and isNum(priceMaximumInput):
            priceMaximum = float(priceMinimumInput)

        if input(f"Is this correct? (Y/n): {priceMaximum if priceMaximum != -1 else "Use no minimum value"}")[0].lower() != 'y':
            continue
        else:
            searchParams["priceMaximum"] = priceMaximum
            break

    while True:
        propertyTypeOptions = []
        propertyTypeInput = input("""Enter the index/indices for the property type(s) you would like to search for:
1: Single Family Listings
2: Condo Listings
3: Townhouse Listings
4: Manufactured Listings
5: Multifamily Listings
6: Apartment Listings
Or press enter to set no listing preferences
Example: "126" would search for Single Family homes, Condos, and Apartments.  
""")
    
        if propertyTypeInput.strip() != "":
            if "1" in propertyTypeInput:
                propertyTypeOptions.append("singlefamily")
            if "2" in propertyTypeInput:
                propertyTypeOptions.append("condo")
            if "3" in propertyTypeInput:
                propertyTypeOptions.append("townhouse")
            if "4" in propertyTypeInput:
                propertyTypeOptions.append("manufactured")
            if "5" in propertyTypeInput:
                propertyTypeOptions.append("multifamily")
            if "6" in propertyTypeInput:
                propertyTypeOptions.append("apartment")

        if input(f"Is this correct? (Y/n): {propertyTypeOptions}")[0].lower() != 'y':
            continue
        else:
            listingTypes = [propertyTypeNames[lt] for lt in propertyTypeOptions if lt in propertyTypeNames.keys()]
            searchParams["propertyTypes"] = listingTypes
            break

    # Save search params into search param file
    searchParamsSave = searchParamExample.copy()
    searchParamsSave["centerAddress"] = centerAddress
    searchParamsSave["workAddress"] = workAddress
    searchParamsSave["searchRadiusMiles"] = searchRadius
    searchParamsSave["priceMinimum"] = priceMinimum
    searchParamsSave["priceMaximum"] = priceMaximum
    searchParamsSave["propertyTypes"] = propertyTypeOptions
    searchParamsFilename = f"searchParams{searchParamsSave["centerAddress"]}{searchParamsSave["searchRadiusMiles"]}.json"
    with open(searchParamsFilename, "w") as f:
        json.dump(searchParamsSave, f, indent=4)

    print(f"Saved searchParams to {searchParamsFilename}")

    return (searchParams, searchParamsFilename)

def generatePOIColumnNames(colNames: List[str], poiCategories: List[str]):
    poiNames = [name.split('.')[-1] for name in poiCategories]

    for name in poiNames:
        durationColumn = f"{name.title()} Dur(min)"
        distanceColumn = f"{name.title()} Dist(mi)"
        colNames.append(durationColumn)
        colNames.append(distanceColumn)

def saveExcel(data: List[dict], colNames: List[str], filename):
    df = pd.DataFrame(data)
    df.columns=colNames
    df.to_excel(filename, index=False, float_format="%.2f")

    print(f"Outputting to {filename}")

def cacheProcessed(processed: list[dict], processedCacheFilename: str):
    if len(processed) == 0:
        print("No processed listings to cache")
        exit(1)

    path = os.path.join("cache/", processedCacheFilename)
    with open(path, "w") as f:
        json.dump(processed, f, indent=4)
    print(f"Saved cache files to {path}")


if __name__ == "__main__":
    main()

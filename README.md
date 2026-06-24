# ApartmentHunter
How to use:
1. Start first search
	1. `python3 main.py --searchParameterFilename [filename]`
2. If there are more listings than rentcast can retrieve, it will cache the current listings and continue processing them. At the end of this stage, you will be left with `RentcastCache.json` and `ProcessedCache.json`. 
	1. `python3 main.py --searchParameterFilename [filename] --rentcastCacheFilename [filename] --processedCacheFilename [filename]`
		1. This will continue searching in that area, starting from what was cached and moving onwards. Then it will process all the unprocessed cached listings and new listings. 
3. If rentcast was able to retrieve all available listings in the area, but openroute service wasn't able to return all the route information for each listing
	1. `python3 main.py --rentcastCacheOnly --rentcastCacheFilename [filename] --processedCacheFilename [filename]`
		1. This will run listings that haven't been processed from the rentcast cache
4. Once all the listings have been processed, it will output an excel file that will store all the information about each listing that you want. 

Essentially, it will store all the listings in that area in a cache file. 
If it wasn't able to retrieve all the listings, you can call the program again with the cached listings, and it will retrieve all the listings it can from there onwards. 
If it wasn't able to process all the listings, it will cache all the listings it currently processed. Then, you will be able to call it again with the cache file, and it will process the remaining listings. 
Repeat until all listings in the area are processed. 

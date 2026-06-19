from pathlib import Path 
import re
import usaddress
from .Models import Address

def parseAddressString(address: str) -> Address | None:
    try:
        parsedAddress, _ = usaddress.tag(address)

        street = re.sub(" +", " ", f"{parsedAddress.get("AddressNumberPrefix", "")} {parsedAddress.get("AddressNumber", "")} {parsedAddress.get("AddressNumberSuffix", "")} {parsedAddress.get("StreetNamePreDirectional", "")} {parsedAddress.get("StreetNamePreModifier", "")} {parsedAddress.get("StreetNamePreType", "")} {parsedAddress.get("StreetName", "")} {parsedAddress.get("StreetNamePostDirectional", "")} {parsedAddress.get("StreetNamePostModifier", "")} {parsedAddress.get("StreetNamePostType", "")}".strip())
        city = re.sub(" +", " ", f"{parsedAddress.get("PlaceName", "")}")
        state = re.sub(" +", " ", f"{parsedAddress.get("StateName", "")}")
        postal = re.sub(" +", " ", f"{parsedAddress.get("ZipCode", "")}")

        res = Address(street=street, city=city, state=state, postal=postal)

        return res
    except usaddress.RepeatedLabelError as e:
        print(f"ERROR: Parsing ideal address. \n{e}")
        return None


def validXLSXFilename(filename: str) -> bool:
    path = Path(filename)
    
    if path.suffix.lower() != '.xlsx':
        return False
        
    invalid_chars = set('<>:"/\\|?*')
    if any(char in invalid_chars for char in path.name):
        return False
        
    if path.stem == "" or path.stem == ".xlsx":
        return False
        
    return True

def isNum(num: str) -> bool:
    try:
        float(num)
        return True
    except ValueError:
        return False

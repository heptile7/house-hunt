from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "house_hunting.db"

INDIAN_CITIES = [
    "Bangalore", "Mumbai", "Delhi", "Chennai", "Hyderabad",
    "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Noida",
    "Gurgaon", "Navi Mumbai", "Thane", "Kochi", "Coimbatore",
    "Surat", "Lucknow", "Bhopal", "Indore", "Nagpur",
]

CITY_SLUGS = {
    "Bangalore":  {"mb": "Bangalore", "99a": "bangalore", "nb": "bangalore",   "hc": "bangalore"},
    "Mumbai":     {"mb": "Mumbai",     "99a": "mumbai",    "nb": "mumbai",      "hc": "mumbai"},
    "Delhi":      {"mb": "Delhi",      "99a": "delhi",     "nb": "delhi",       "hc": "delhi"},
    "Chennai":    {"mb": "Chennai",    "99a": "chennai",   "nb": "chennai",     "hc": "chennai"},
    "Hyderabad":  {"mb": "Hyderabad",  "99a": "hyderabad", "nb": "hyderabad",   "hc": "hyderabad"},
    "Pune":       {"mb": "Pune",       "99a": "pune",      "nb": "pune",        "hc": "pune"},
    "Kolkata":    {"mb": "Kolkata",    "99a": "kolkata",   "nb": "kolkata",     "hc": "kolkata"},
    "Ahmedabad":  {"mb": "Ahmedabad",  "99a": "ahmedabad", "nb": "ahmedabad",   "hc": "ahmedabad"},
    "Jaipur":     {"mb": "Jaipur",     "99a": "jaipur",    "nb": "jaipur",      "hc": "jaipur"},
    "Noida":      {"mb": "Noida",      "99a": "noida",     "nb": "noida",       "hc": "noida"},
    "Gurgaon":    {"mb": "Gurgaon",    "99a": "gurgaon",   "nb": "gurgaon",     "hc": "gurugram"},
    "Navi Mumbai":{"mb": "Navi-Mumbai","99a": "navi-mumbai","nb": "navi-mumbai", "hc": "navi-mumbai"},
    "Thane":      {"mb": "Thane",      "99a": "thane",     "nb": "thane",       "hc": "thane"},
    "Kochi":      {"mb": "Kochi",      "99a": "kochi",     "nb": "kochi",       "hc": "kochi"},
    "Coimbatore": {"mb": "Coimbatore", "99a": "coimbatore","nb": "coimbatore",  "hc": "coimbatore"},
}

# City → state, used for stamp duty / registration rates in the EMI calculator.
CITY_STATE = {
    "Bangalore": "Karnataka", "Chennai": "Tamil Nadu", "Coimbatore": "Tamil Nadu",
    "Hyderabad": "Telangana", "Mumbai": "Maharashtra", "Navi Mumbai": "Maharashtra",
    "Thane": "Maharashtra", "Pune": "Maharashtra", "Nagpur": "Maharashtra",
    "Delhi": "Delhi", "Noida": "Uttar Pradesh", "Lucknow": "Uttar Pradesh",
    "Gurgaon": "Haryana", "Kolkata": "West Bengal", "Kochi": "Kerala",
    "Ahmedabad": "Gujarat", "Surat": "Gujarat", "Jaipur": "Rajasthan",
    "Bhopal": "Madhya Pradesh", "Indore": "Madhya Pradesh",
}

PROPERTY_TYPES =["All", "Apartment", "Villa", "Independent House", "Plot", "Builder Floor", "Penthouse"]

BHK_OPTIONS = [1, 2, 3, 4, 5]

SCRAPER_CONFIG = {
    "update_interval_hours": 6,
    "request_delay_seconds": 2.5,
    "max_retries": 3,
    "timeout_seconds": 20,
    "max_pages_per_source": 5,
}

SOURCES = ["magicbricks", "99acres", "nobroker", "housing"]

SOURCE_LABELS = {
    "magicbricks": "MagicBricks",
    "99acres":     "99acres",
    "nobroker":    "NoBroker",
    "housing":     "Housing.com",
}

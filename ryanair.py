import requests
from collections import defaultdict
import json

airports_raw = requests.get("https://www.ryanair.com/api/locate/v1/autocomplete/airports?phrase=&market=de-de").json()
airports = {rr["code"]:rr for rr in airports_raw}

def get_availability(Origin, Destination, availabilitie):
    url = f"https://www.ryanair.com/api/booking/v4/de-de/availability?ADT=1&CHD=0&DateIn=&DateOut={availabilitie}&Destination={Destination}&Disc=0&INF=0&Origin={Origin}&TEEN=0&promoCode=&IncludeConnectingFlights=false&FlexDaysBeforeOut=0&FlexDaysOut=0&ToUs=AGREED"
    r4 = requests.get(url).json()
    r = set()
    for date in r4["trips"][0]["dates"]:
        for flight in date["flights"]:
            if flight["faresLeft"] > 0:
                r.add((flight["regularFare"]["fares"][0]["amount"], flight["timeUTC"][0], flight["timeUTC"][1], r4["currency"]))
    return r
  
flight_info = defaultdict(lambda: defaultdict(lambda: defaultdict(tuple)))
for Origin in airports:
    r2 = requests.get(f"https://www.ryanair.com/api/locate/v1/autocomplete/routes?arrivalPhrase=&departurePhrase={Origin}&market=de-de").json()
    Destinations = {arrivalAirport["arrivalAirport"]["code"]:arrivalAirport["arrivalAirport"]["coordinates"] for arrivalAirport in r2}
    for Destination in Destinations:
        availabilities = requests.get(f"https://www.ryanair.com/api/farfnd/3/oneWayFares/{Origin}/{Destination}/availabilities").json()
        for availabilitie in availabilities:
            for price, start, end, currency in get_availability(Origin, Destination, availabilitie):
                flight_info[Origin][Destination][start] = price, end, currency

json.dump(flight_info, open("flight_info.json", "w+"))

import requests
from collections import defaultdict
import json


def get_airports():
    airports_raw = requests.get("https://www.ryanair.com/api/locate/v1/autocomplete/airports?phrase=&market=de-de").json()
    return {rr["code"]:rr for rr in airports_raw}


def get_destinations(origin):
    r2 = requests.get(f"https://www.ryanair.com/api/locate/v1/autocomplete/routes?arrivalPhrase=&departurePhrase={origin}&market=de-de").json()
    return {arrivalAirport["arrivalAirport"]["code"] for arrivalAirport in r2 if arrivalAirport["connectingAirport"] is None}


def get_availabilities(origin, destination):
    return requests.get(f"https://www.ryanair.com/api/farfnd/3/oneWayFares/{origin}/{destination}/availabilities").json()


def get_flights(origin, destination, availabilitie):
    url = f"https://www.ryanair.com/api/booking/v4/de-de/availability?ADT=1&CHD=0&DateIn=&DateOut={availabilitie}&Destination={destination}&Disc=0&INF=0&Origin={origin}&TEEN=0&promoCode=&IncludeConnectingFlights=false&FlexDaysBeforeOut=0&FlexDaysOut=0&ToUs=AGREED"
    r4 = requests.get(url).json()
    r = set()
    for date in r4["trips"][0]["dates"]:
        for flight in date["flights"]:
            if flight["faresLeft"] > 0:
                r.add((flight["regularFare"]["fares"][0]["amount"], flight["timeUTC"][0], flight["timeUTC"][1], r4["currency"]))
    return r


if __name__ == "__main__":
    flight_info = defaultdict(lambda: defaultdict(lambda: defaultdict(tuple)))
    for origin in get_airports():
        for destination in get_destinations(origin):
            for availabilitie in get_availabilities(origin, destination):
                for price, start, end, currency in get_flights(origin, destination, availabilitie):
                    flight_info[origin][destination][start] = price, end, currency

    json.dump(flight_info, open("flight_info.json", "w+"))

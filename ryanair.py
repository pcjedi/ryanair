import requests
from collections import defaultdict
import json
from functools import cache
from dateutil import parser
from tqdm import tqdm
import datetime



class Flight:
    def __init__(self, start, end, origin, destination, amount, currency):
        self.start = start
        self.end = end
        self.origin = origin
        self.destination = destination
        self.amount = amount
        self.currency = currency
    
    def __repr__(self):
        return f"{self.origin}-{self.destination}:{self.start.strftime('%Y-%m-%d/%H:%M')}{self.currency}{self.amount}"
        
    @property
    def euro(self):
        return self.amount / get_rates()[self.currency]
    
    @property
    def url(self):
        return f"https://www.ryanair.com/de/de/trip/flights/select?adults=1&teens=0&children=0&infants=0&dateOut={self.start.strftime('%Y-%m-%d')}&dateIn=&isConnectedFlight=false&isReturn=false&discount=0&promoCode=&originIata={self.origin}&destinationIata={self.destination}&tpAdults=1&tpTeens=0&tpChildren=0&tpInfants=0&tpStartDate={self.start.strftime('%Y-%m-%d')}&tpEndDate=&tpDiscount=0&tpPromoCode=&tpOriginIata={self.origin}&tpDestinationIata={self.destination}"


@cache
def get_airports():
    airports_raw = requests.get("https://www.ryanair.com/api/locate/v1/autocomplete/airports?phrase=&market=de-de").json()
    return {rr["code"]:rr for rr in airports_raw}


@cache
def get_destinations(origin):
    r2 = requests.get(f"https://www.ryanair.com/api/locate/v1/autocomplete/routes?arrivalPhrase=&departurePhrase={origin}&market=de-de").json()
    return {arrivalAirport["arrivalAirport"]["code"] for arrivalAirport in r2 if arrivalAirport["connectingAirport"] is None}


@cache
def get_availabilities(origin, destination):
    return [parser.parse(d).date() for d in requests.get(f"https://www.ryanair.com/api/farfnd/3/oneWayFares/{origin}/{destination}/availabilities").json()]


@cache
def get_flights(origin, destination, availabilitie):
    url = f"https://www.ryanair.com/api/booking/v4/de-de/availability?ADT=1&CHD=0&DateIn=&DateOut={availabilitie.strftime('%Y-%m-%d')}&Destination={destination}&Disc=0&INF=0&Origin={origin}&TEEN=0&promoCode=&IncludeConnectingFlights=false&FlexDaysBeforeOut=0&FlexDaysOut=0&ToUs=AGREED"
    r4 = requests.get(url).json()
    r = set()
    for date in r4["trips"][0]["dates"]:
        for flight in date["flights"]:
            if flight["faresLeft"] > 0:
                r.add(
                    Flight(
                        start = parser.parse(flight["timeUTC"][0]),
                        end = parser.parse(flight["timeUTC"][1]),
                        origin = origin,
                        destination = destination,
                        amount = float(flight["regularFare"]["fares"][0]["amount"]),
                        currency = r4["currency"],
                    )
                )
    return r


@cache
def get_rates(base="EUR"):
    return requests.get(f"https://api.exchangerate.host/latest?base={base}").json()["rates"]


def min_route(r):
    if r is None:
        return
    if len(r)==0:
        return []
    routes = []
    for k,v in r.items():
        v2 = min_route(v)
        if v2 is None:
            r[k] = None
        else:
            routes.append([k] + v2)
    if len(routes)==0:
        return
    return sorted(
        routes,
        key=lambda route:sum(f.euro for f in route)/len(route)
    )[0]


def get(r, l):
    if len(l)==1:
        return r[l[0]]
    return get(r[l[0]], l[1:])


def set_none(r, l):
    if len(l)==1:
        r[l[0]] = None
    else:
        set_none(r[l[0]], l[1:])


if __name__ == "__main__":
    import argparse
    aparser = argparse.ArgumentParser()
    aparser.add_argument('--root_origin')
    aparser.add_argument('--start_within', type=int)
    aparser.add_argument('--min_stay', type=int)
    aparser.add_argument('--max_stay', type=int)
    aparser.add_argument('--max_away', type=int)
    aparser.add_argument('--no_tqdm', action='store_true')
    args = aparser.parse_args()
    
    r = dict()
    cheapest_route = None
    
    a = get_airports()
    assert args.root_origin in a
    
    for dest in get_destinations(args.root_origin):
        for date in tqdm(get_availabilities(args.root_origin, dest), desc=dest, disable=args.no_tqdm):
            if date < datetime.date.today() + datetime.timedelta(args.start_within):
                for flight in get_flights(args.root_origin, dest, date):
                    if flight not in r:
                        r[flight] = {}
    
    mr = min_route(r)
    while mr is not None:
        for dest in tqdm(get_destinations(mr[-1].destination), desc=mr[-1].destination, disable=args.no_tqdm):
            if dest not in {f.destination for f in mr}:
                for date in get_availabilities(mr[-1].destination, dest):
                    if 0 <= (date - mr[-1].end.date()).days <= 1 + args.max_stay / 24 and (date - mr[0].start.date()).days < args.max_away:
                        for flight in get_flights(mr[-1].destination, dest, date):
                            if 3600 * args.min_stay < (flight.end - mr[-1].end).total_seconds() < 3600 * args.max_stay:
                                if flight.destination==args.root_origin:
                                    if cheapest_route is None or (sum(f.euro for f in cheapest_route)/len(cheapest_route))>(sum(f.euro for f in mr + [flight])/len(mr + [flight])):
                                        cheapest_route = mr + [flight]
                                        print(cheapest_route)
                                        [print(f.url) for f in cheapest_route]
                                else:
                                    get(r, mr)[flight] = {}

        if len(get(r, mr))==0:
            set_none(r, mr)

        mr = min_route(r)

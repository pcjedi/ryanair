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
    def duration(self):
        return self.end - self.start
    
    @property
    def url(self):
        return f"https://www.ryanair.com/de/de/trip/flights/select?adults=1&teens=0&children=0&infants=0&dateOut={self.start.strftime('%Y-%m-%d')}&dateIn=&isConnectedFlight=false&isReturn=false&discount=0&promoCode=&originIata={self.origin}&destinationIata={self.destination}&tpAdults=1&tpTeens=0&tpChildren=0&tpInfants=0&tpStartDate={self.start.strftime('%Y-%m-%d')}&tpEndDate=&tpDiscount=0&tpPromoCode=&tpOriginIata={self.origin}&tpDestinationIata={self.destination}"


@cache
def get_airports(session=requests):
    g = session.get("https://www.ryanair.com/api/locate/v1/autocomplete/airports?phrase=&market=de-de")
    airports_raw = g.json()
    return {rr["code"]:rr for rr in airports_raw}


@cache
def get_destinations(origin, session=requests):
    g = session.get(f"https://www.ryanair.com/api/locate/v1/autocomplete/routes?arrivalPhrase=&departurePhrase={origin}&market=de-de")
    r2 = g.json()
    return {arrivalAirport["arrivalAirport"]["code"] for arrivalAirport in r2 if arrivalAirport["connectingAirport"] is None}


@cache
def get_availabilities(origin, destination, session=requests):
    g = session.get(f"https://www.ryanair.com/api/farfnd/3/oneWayFares/{origin}/{destination}/availabilities")
    return [parser.parse(d).date() for d in g.json()]


@cache
def get_flights(origin, destination, availabilitie, session=requests):
    url = f"https://www.ryanair.com/api/booking/v4/de-de/availability?ADT=1&CHD=0&DateIn=&DateOut={availabilitie.strftime('%Y-%m-%d')}&Destination={destination}&Disc=0&INF=0&Origin={origin}&TEEN=0&promoCode=&IncludeConnectingFlights=false&FlexDaysBeforeOut=0&FlexDaysOut=0&ToUs=AGREED"
    g = session.get(url)
    r4 = g.json()
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
def get_rates(base="EUR", session=requests):
    g = session.get(f"https://api.exchangerate.host/latest?base={base}")
    return g.json()["rates"]


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
    aparser.add_argument('--early_quit', action='store_true')
    args = aparser.parse_args()
    
    start_time = datetime.datetime.now()
    
    r = dict()
    cheapest_route = None

    s = requests.Session()
    a = get_airports(session=s)
    assert args.root_origin in a
    
    for dest in get_destinations(args.root_origin, session=s):
        for date in tqdm(get_availabilities(args.root_origin, dest, session=s), desc=dest, disable=args.no_tqdm):
            if date < datetime.date.today() + datetime.timedelta(args.start_within):
                for flight in get_flights(args.root_origin, dest, date, session=s):
                    if flight not in r:
                        r[flight] = {}
    
    mr = min_route(r)
    while mr is not None:
        for dest in tqdm(get_destinations(mr[-1].destination, session=s), desc=mr[-1].destination, disable=args.no_tqdm):
            if dest not in {f.destination for f in mr}:
                for date in get_availabilities(mr[-1].destination, dest, session=s):
                    if 0 <= (date - mr[-1].end.date()).days <= 1 + args.max_stay / 24 and (date - mr[0].start.date()).days < args.max_away:
                        for flight in get_flights(mr[-1].destination, dest, date, session=s):
                            if 3600 * args.min_stay < (flight.end - mr[-1].end).total_seconds() < 3600 * args.max_stay:
                                if flight.destination==args.root_origin:
                                    if cheapest_route is None or (sum(f.euro for f in cheapest_route)/len(cheapest_route))>(sum(f.euro for f in mr + [flight])/len(mr + [flight])):
                                        cheapest_route = mr + [flight]
                                        print(
                                            sum(f.euro for f in cheapest_route),
                                            len(cheapest_route),
                                            sum(f.euro for f in cheapest_route)/len(cheapest_route),
                                            cheapest_route,
                                            [(a[f1.destination]["name"], str(f1.end-f1.start), str(f2.start-f1.end)) for f1,f2 in zip(cheapest_route, cheapest_route[1:])],
                                            [f.url for f in cheapest_route],
                                            str(datetime.datetime.now() - start_time),
                                        )
                                else:
                                    get(r, mr)[flight] = {}
        
        if len(get(r, mr))==0:
            set_none(r, mr)

        mr = min_route(r)

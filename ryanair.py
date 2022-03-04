import requests
from collections import defaultdict
import json
from functools import cache
from dateutil import parser
from tqdm import tqdm
import datetime
import time
import uuid
from tenacity import retry, retry_if_exception_type, wait_exponential, stop_after_attempt


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

    def update(self, session=requests, update=None, amount_update=None):
        if update is None:
            update = uuid.uuid4()
        for f in get_flights(
            origin=self.origin,
            destination=self.destination,
            availabilitie=self.start,
            session=session,
            update=update,
            ):
            if f.start == self.start:
                amount_update = f.amount
        self.amount = amount_update


@cache
@retry(stop=stop_after_attempt(7), retry=(retry_if_exception_type(json.decoder.JSONDecodeError) | retry_if_exception_type(KeyError) | retry_if_exception_type(requests.exceptions.ConnectionError) ), wait=wait_exponential(multiplier=1, min=0, max=70))
def get_airports(session=requests):
    url = "https://www.ryanair.com/api/locate/v1/autocomplete/airports"
    airports = {airport["code"]:airport for airport in json.load(open("airports.json", "r"))}
    airports |= {airport["code"]:airport for airport in session.get(url).json()}
    json.dump(airports, open("airports.json", "w"))
    return airports


@cache
@retry(stop=stop_after_attempt(7), retry=(retry_if_exception_type(json.decoder.JSONDecodeError) | retry_if_exception_type(KeyError) | retry_if_exception_type(requests.exceptions.ConnectionError) ), wait=wait_exponential(multiplier=1, min=0, max=70))
def get_destinations(origin, session=requests):
    g = session.get(f"https://www.ryanair.com/api/locate/v1/autocomplete/routes?arrivalPhrase=&departurePhrase={origin}&market=de-de")
    r2 = g.json()
    return {arrivalAirport["arrivalAirport"]["code"] for arrivalAirport in r2 if arrivalAirport["connectingAirport"] is None}


@cache
@retry(stop=stop_after_attempt(7), retry=(retry_if_exception_type(json.decoder.JSONDecodeError) | retry_if_exception_type(KeyError) | retry_if_exception_type(requests.exceptions.ConnectionError) ), wait=wait_exponential(multiplier=1, min=0, max=70))
def get_availabilities(origin, destination, session=requests):
    g = session.get(f"https://www.ryanair.com/api/farfnd/3/oneWayFares/{origin}/{destination}/availabilities")
    return [parser.parse(d).date() for d in g.json()]


@cache
@retry(stop=stop_after_attempt(7), retry=(retry_if_exception_type(json.decoder.JSONDecodeError) | retry_if_exception_type(KeyError) | retry_if_exception_type(requests.exceptions.ConnectionError) ), wait=wait_exponential(multiplier=1, min=0, max=70))
def get_flights(origin, destination, availabilitie, session=requests, update=None):
    url = f"https://www.ryanair.com/api/booking/v4/availability?ADT=1&CHD=0&DateIn=&DateOut={availabilitie.strftime('%Y-%m-%d')}&Destination={destination}&Disc=0&INF=0&Origin={origin}&TEEN=0&promoCode=&IncludeConnectingFlights=false&FlexDaysBeforeOut=0&FlexDaysOut=0&ToUs=AGREED"
    r = set()
    gurl= session.get(url)
    r4 = gurl.json()
    try:
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
    except KeyError as e:
        print(e, r4, url)
        raise
    return r


@cache
@retry(stop=stop_after_attempt(7), retry=(retry_if_exception_type(json.decoder.JSONDecodeError) | retry_if_exception_type(KeyError) | retry_if_exception_type(requests.exceptions.ConnectionError) ), wait=wait_exponential(multiplier=1, min=0, max=70))
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
    aparser.add_argument('--root_origin_code')
    aparser.add_argument('--start_within_days', type=int)
    aparser.add_argument('--min_stay_hours', type=int)
    aparser.add_argument('--max_stay_hours', type=int)
    aparser.add_argument('--max_away_days', type=int)
    aparser.add_argument('--no_tqdm', action='store_true')
    aparser.add_argument('--early_quit', action='store_true')
    aparser.add_argument('--unique_country', action='store_true')
    aparser.add_argument('--country_blacklist', nargs='*', default=[])
    aparser.add_argument('--blacklist', nargs='*', default=[])
    aparser.add_argument('--country_whitelist', nargs='*', default=[])
    aparser.add_argument('--whitelist', nargs='*', default=[])
    args = aparser.parse_args()

    
    start_time = datetime.datetime.now()
    
    r = dict()

    s = requests.Session()
    a = get_airports(session=s)
    print(f"found {len(a)} airports: {a.keys()}")

    countries = {aa["country"]["code"]:aa["country"]["name"] for aa in a.values()}
    whitelist = set(args.whitelist)
    country_blacklist = set(args.country_blacklist)
    blacklist = set(args.blacklist)
    country_whitelist = set(args.country_whitelist)

    assert args.root_origin_code in a, f"root_origin_code must be one of {set(a.keys())}"
    assert country_blacklist - set(countries.keys()) == set(), f"country black list items must all be in {countries}"
    assert country_whitelist - set(countries.keys()) == set(), f"country white list items must all be in {countries}"
    assert blacklist - set(a.keys()) == set(), f"blacklisted must be in {a.keys()}"

    print(f"{ len(country_blacklist) } countries blacklisted, airports: { {aa['name'] for aa in a.values() if aa['country']['code'] in country_blacklist} }")
    print({a[dest]["name"]:a[dest]["country"]["code"] not in country_blacklist for dest in a})


    for dest in get_destinations(args.root_origin_code, session=s):
        if (len(whitelist)==0 or dest in whitelist) and \
        (len(country_whitelist)==0 or a[dest]["country"]["code"] in country_whitelist) and \
        a[dest]["country"]["code"] not in country_blacklist and \
        dest not in blacklist:
            for date in tqdm(get_availabilities(args.root_origin_code, dest, session=s), desc=dest, disable=args.no_tqdm):
                if date < datetime.date.today() + datetime.timedelta(args.start_within_days):
                    for flight in get_flights(args.root_origin_code, dest, date, session=s):
                        if flight not in r:
                            r[flight] = {}

    mr = min_route(r)
    closed_routes = []
    while mr is not None and (datetime.datetime.now() - start_time).total_seconds() < 3600 * 5.8:
        for dest in tqdm(get_destinations(mr[-1].destination, session=s), desc=mr[-1].destination, disable=args.no_tqdm):
            if dest==args.root_origin_code or \
            dest not in {f.destination for f in mr} and \
            (len(whitelist)==0 or dest in whitelist) and \
            (len(country_whitelist)==0 or a[dest]["country"]["code"] in country_whitelist) and \
            dest not in blacklist and \
            a[dest]["country"]["code"] not in country_blacklist and \
            (not args.unique_country or a[dest]["country"]["code"] not in {a[f.destination]["country"]["code"] for f in mr}):
                for date in get_availabilities(mr[-1].destination, dest, session=s):
                    if 0 <= (date - mr[-1].end.date()).days <= 1 + args.max_stay_hours / 24 and (date - mr[0].start.date()).days < args.max_away_days:
                        for flight in get_flights(mr[-1].destination, dest, date, session=s):
                            if 3600 * args.min_stay_hours < (flight.start - mr[-1].end).total_seconds() < 3600 * args.max_stay_hours:
                                if flight.destination==args.root_origin_code:
                                    closed_routes.append(mr + [flight])
                                else:
                                    get(r, mr)[flight] = {}

        if len(get(r, mr))==0:
            set_none(r, mr)

        mr = min_route(r)

    print(f"found {len(closed_routes)} closed routes")
    update = uuid.uuid4()
    [f.update(session=s, update=update) for r in closed_routes for f in r]
    
    for route in sorted(
        filter(
            lambda r: not any(f.amount is None for f in r),
            closed_routes,
        ),
        key=lambda r:sum(f.euro for f in r)/(len(r)-1),
    ):
        print(
            sum(f.euro for f in route),
            len(route),
            sum(f.euro for f in route)/len(route),
            route[0].start,
            route[-1].end,
            route,
            [(a[f1.destination]["name"], str(f1.end-f1.start), str(f2.start-f1.end)) for f1,f2 in zip(route, route[1:])],
            [f.url for f in route],
        )

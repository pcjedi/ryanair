import requests
import os
from collections import defaultdict, Counter
import json
from functools import cache
from dateutil import parser
import datetime
import time
import uuid
from tenacity import retry, retry_if_exception_type, wait_exponential, stop_after_attempt
from typing import List, Set
from calendar import day_name
from itertools import permutations, product


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
        return (
            "https://www.ryanair.com/de/de/trip/flights/select?"
            "adults=1&"
            "teens=0&"
            "children=0&"
            "infants=0&"
            f"dateOut={self.start.strftime('%Y-%m-%d')}&"
            "dateIn=&"
            "isConnectedFlight=false&"
            "isReturn=false&"
            "discount=0&"
            "promoCode=&"
            f"originIata={self.origin}&"
            f"destinationIata={self.destination}&"
            "tpAdults=1&"
            "tpTeens=0&"
            "tpChildren=0&"
            "tpInfants=0&"
            f"tpStartDate={self.start.strftime('%Y-%m-%d')}&"
            "tpEndDate=&"
            "tpDiscount=0&"
            "tpPromoCode=&"
            f"tpOriginIata={self.origin}&"
            f"tpDestinationIata={self.destination}"
        )

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
@retry(
    stop=stop_after_attempt(7),
    retry=(
        retry_if_exception_type(json.decoder.JSONDecodeError)
        | retry_if_exception_type(KeyError)
        | retry_if_exception_type(requests.exceptions.ConnectionError)
    ),
    wait=wait_exponential(multiplier=1, min=0, max=70),
)
def get_airports(session=requests):
    url = "https://www.ryanair.com/api/locate/v1/autocomplete/airports"
    airports = {airport["code"]: airport for airport in json.load(open("airports.json", "r"))}
    airports |= {airport["code"]: airport for airport in session.get(url).json()}
    return airports


@cache
@retry(
    stop=stop_after_attempt(7),
    retry=(
        retry_if_exception_type(json.decoder.JSONDecodeError)
        | retry_if_exception_type(KeyError)
        | retry_if_exception_type(requests.exceptions.ConnectionError)
    ),
    wait=wait_exponential(multiplier=1, min=0, max=70),
)
def get_destinations(origin, session=requests):
    g = session.get(
        f"https://www.ryanair.com/api/locate/v1/autocomplete/routes?arrivalPhrase=&departurePhrase={origin}&market=de-de"
    )
    r2 = g.json()
    return {arrivalAirport["arrivalAirport"]["code"] for arrivalAirport in r2 if arrivalAirport["connectingAirport"] is None}


@cache
@retry(
    stop=stop_after_attempt(7),
    retry=(
        retry_if_exception_type(json.decoder.JSONDecodeError)
        | retry_if_exception_type(KeyError)
        | retry_if_exception_type(requests.exceptions.ConnectionError)
    ),
    wait=wait_exponential(multiplier=1, min=0, max=70),
)
def get_availabilities(origin, destination, session=requests):
    g = session.get(f"https://www.ryanair.com/api/farfnd/3/oneWayFares/{origin}/{destination}/availabilities")
    return [parser.parse(d).date() for d in g.json()]


@cache
@retry(
    stop=stop_after_attempt(7),
    retry=(
        retry_if_exception_type(json.decoder.JSONDecodeError)
        | retry_if_exception_type(KeyError)
        | retry_if_exception_type(requests.exceptions.ConnectionError)
    ),
    wait=wait_exponential(multiplier=1, min=0, max=70),
)
def get_flights(origin, destination, availabilitie, session=requests, update=None, sleep=None, mailto=None):
    url = (
        "https://www.ryanair.com/api/booking/v4/availability?"
        "ADT=1&"
        "CHD=0&"
        "DateIn=&"
        f"DateOut={availabilitie.strftime('%Y-%m-%d')}&"
        f"Destination={destination}&"
        "Disc=0&"
        "INF=0&"
        f"Origin={origin}&"
        "TEEN=0&"
        "promoCode=&"
        "IncludeConnectingFlights=false&"
        "FlexDaysBeforeOut=0&"
        "FlexDaysOut=0&"
        "ToUs=AGREED"
    )
    if "mailto" in os.environ:
        url += f"&mailto={os.getenv('mailto')}"
    r = set()
    if sleep is not None:
        time.sleep(sleep)
    gurl = session.get(url)
    r4 = gurl.json()
    try:
        for date in r4["trips"][0]["dates"]:
            for flight in date["flights"]:
                if flight["faresLeft"] > 0:
                    r.add(
                        Flight(
                            start=parser.parse(flight["timeUTC"][0]),
                            end=parser.parse(flight["timeUTC"][1]),
                            origin=origin,
                            destination=destination,
                            amount=float(flight["regularFare"]["fares"][0]["amount"]),
                            currency=r4["currency"],
                        )
                    )
    except KeyError as e:
        print(e, r4, url)
        raise
    return r


def get_fare_origins(origins, **kwargs) -> Set[Flight]:
    return {f for origin in origins for f in get_fare(origin=origin, **kwargs)}


@cache
def get_fare(origin, start, end, session=requests, sleep=None) -> Set[Flight]:
    if sleep is not None:
        time.sleep(sleep)
    url = "https://services-api.ryanair.com/farfnd/3/oneWayFares"
    params = {
        "departureAirportIataCode": origin,
        "outboundDepartureDateFrom": start.strftime("%Y-%m-%d"),
        "outboundDepartureDateTo": end.strftime("%Y-%m-%d"),
    }
    if "mailto" in os.environ:
        params["mailto"] = os.getenv("mailto")
    fares = set()
    for fare in session.get(url=url, params=params).json()["fares"]:
        destination = fare["outbound"]["arrivalAirport"]["iataCode"]
        if destination in get_destinations(origin, session=session):
            fares.add(
                Flight(
                    origin=fare["outbound"]["departureAirport"]["iataCode"],
                    destination=destination,
                    start=parser.parse(fare["outbound"]["departureDate"]),
                    end=parser.parse(fare["outbound"]["arrivalDate"]),
                    amount=fare["outbound"]["price"]["value"],
                    currency=fare["outbound"]["price"]["currencyCode"],
                )
            )
    return fares


@cache
@retry(
    stop=stop_after_attempt(7),
    retry=(
        retry_if_exception_type(json.decoder.JSONDecodeError)
        | retry_if_exception_type(KeyError)
        | retry_if_exception_type(requests.exceptions.ConnectionError)
    ),
    wait=wait_exponential(multiplier=1, min=0, max=70),
)
def get_rates(base="EUR", session=requests):
    g = session.get(f"https://api.exchangerate.host/latest?base={base}")
    return g.json()["rates"]


def get_connections(origin, destination, max_depth=1, path=[], blacklist=set()):
    destinations = get_destinations(origin) - set(path) - blacklist
    if destination in destinations:
        return [path + [origin] + [destination]]
    elif max_depth > 0:
        r_list = []
        for dest in destinations:
            result_list = get_connections(dest, destination, max_depth - 1, path + [origin], blacklist=blacklist)
            for result in result_list:
                if result[-1] == destination:
                    r_list.append(result)
        return r_list
    else:
        return []


def get_connecting_lists(origin, destination, blacklist=set()):
    connections = []
    max_depth = 0
    while len(connections) == 0:
        connections += get_connections(origin, destination, max_depth, blacklist=blacklist)
        max_depth += 1
    return connections


def get_starts(origin, destinations, blacklist=set()):
    starts = []
    if len(destinations) == 0:
        return starts
    for dests in permutations(destinations, len(destinations)):
        starts_temp = get_connecting_lists(origin, list(dests)[0], blacklist=blacklist)
        for o, d in zip(list(dests)[:-1], list(dests)[1:]):
            starts_temp = [
                l1 + l2[1:]
                for l1, l2 in product(starts_temp, get_connecting_lists(o, d, blacklist=blacklist))
                if len(l1 + l2[1:]) == len(set(l1) | set(l2[1:]))
            ]
        starts += starts_temp
    return starts


def min_route(r) -> List[Flight]:
    if r is None:
        return
    if len(r) == 0:
        return []
    routes = []
    for k, v in r.items():
        v2 = min_route(v)
        if v2 is None:
            r[k] = None
        else:
            routes.append([k] + v2)
    try:
        return min(routes, key=lambda route: sum(f.euro for f in route) / (len(route) - 1))
    except ZeroDivisionError:
        return min(routes, key=lambda route: route[0].euro)
    except ValueError:
        return


def getter(r, key_list: list):
    if len(key_list) == 1:
        return r[key_list[0]]
    return getter(r[key_list[0]], key_list[1:])


def setter(r, key_list: list, value=None):
    if len(key_list) == 1:
        r[key_list[0]] = value
    else:
        setter(r[key_list[0]], key_list[1:], value)


def routes_finder(
    airports,
    root_origin_code,
    start_not_before,
    start_until,
    max_away_days,
    min_stay_days,
    cityairports,
    unique_country=False,
    country_whitelist=None,
    blacklist=set(),
    max_routes=None,
    allowed_starts=[],
    sleep=None,
    session=requests,
):
    start_time = datetime.datetime.now()
    r = dict()
    for flight in get_fare(
        origin=root_origin_code,
        start=start_not_before,
        end=start_until,
        session=session,
        sleep=sleep,
    ):
        if (
            (len(country_whitelist) == 0 or airports[flight.destination]["country"]["code"] in country_whitelist)
            and flight.destination not in blacklist
            and (
                len(allowed_starts) == 0
                or any(all(s == f.destination for s, f in zip(start[1:], [flight])) for start in allowed_starts)
            )
        ):
            r[flight] = {}

    closed_routes = dict()
    mr = min_route(r)

    while (
        mr is not None
        and (max_routes is None or len(closed_routes) < max_routes)
        and (datetime.datetime.now() - start_time).total_seconds() < 3600 * 5
    ):
        for days in range(min_stay_days, max_away_days - (mr[-1].end - mr[0].start).days):
            for flight in get_fare_origins(
                origins=cityairports[city(mr[-1].destination)],
                start=mr[-1].end.date() + datetime.timedelta(days + 1),
                end=mr[-1].end.date() + datetime.timedelta(days + 1),
                session=session,
                sleep=sleep,
            ):
                if city(flight.destination) == city(root_origin_code) and (
                    len(allowed_starts) == 0
                    or any(start == [f.origin for f in (mr + [flight])[: len(start)]] for start in allowed_starts)
                ):
                    old_route = closed_routes.get(tuple(sorted(city(f.destination) for f in mr)), None)
                    new_route = mr + [flight]
                    if old_route is None or sum(f.euro for f in new_route) < sum(f.euro for f in old_route):
                        closed_routes[tuple(sorted(city(f.destination) for f in mr))] = mr + [flight]
                elif (
                    (len(country_whitelist) == 0 or airports[flight.destination]["country"]["code"] in country_whitelist)
                    and (
                        not unique_country
                        or airports[flight.destination]["country"]["code"]
                        not in {airports[flight.destination]["country"]["code"] for f in mr}
                    )
                    and city(flight.destination) not in {city(f.destination) for f in mr}
                    and flight.destination not in blacklist
                    and (
                        len(allowed_starts) == 0
                        or any(all(s == f.destination for s, f in zip(start[1:], mr + [flight])) for start in allowed_starts)
                    )
                ):
                    getter(r, mr)[flight] = {}
        if len(getter(r, mr)) == 0:
            setter(r, mr)
        mr = min_route(r)

    return list(closed_routes.values())


def flexdate(s: str) -> datetime.date:
    try:
        return datetime.datetime.now().date() + datetime.timedelta(days=int(s))
    except ValueError:
        return parser.parse(s).date()


if __name__ == "__main__":
    import argparse

    aparser = argparse.ArgumentParser()
    aparser.add_argument("--root_origin_code")
    aparser.add_argument("--start_not_before", type=flexdate)
    aparser.add_argument("--start_until", type=flexdate)
    aparser.add_argument("--max_away_days", type=int)
    aparser.add_argument("--min_stay_days", type=int)
    aparser.add_argument("--early_quit", action="store_true")
    aparser.add_argument("--unique_country", action="store_true")
    aparser.add_argument("--country_blacklist", nargs="*", default=[])
    aparser.add_argument("--blacklist", nargs="*", default=[])
    aparser.add_argument("--country_whitelist", nargs="*", default=[])
    aparser.add_argument("--whitelist", nargs="*", default=[])
    aparser.add_argument("--via", nargs="*", default=[])
    aparser.add_argument("--max_routes", type=int)
    aparser.add_argument("--sleep", type=float)
    args = aparser.parse_args()

    start_time = datetime.datetime.now()

    s = requests.Session()
    a = get_airports(session=s)

    countries = {aa["country"]["code"]: aa["country"]["name"] for aa in a.values()}
    whitelist = set(args.whitelist)
    country_blacklist = set(args.country_blacklist)
    blacklist = set(args.blacklist)
    country_whitelist = set(args.country_whitelist)

    assert args.root_origin_code in a, f"root_origin_code must be one of {set(a.keys())}"
    assert country_blacklist - set(countries.keys()) == set(), f"country black list items must all be in {countries}"
    assert country_whitelist - set(countries.keys()) == set(), f"country white list items must all be in {countries}"
    assert blacklist - set(a.keys()) == set(), f"blacklisted must be in {a.keys()}"

    def city(airport):
        return a[airport].get("macCity", a[airport]["city"])["code"].capitalize()

    cityairports = defaultdict(set)
    [cityairports[city(code)].add(code) for code in a]
    allowed_starts = get_starts(origin=args.root_origin_code, destinations=args.via, blacklist=blacklist)

    closed_routes = routes_finder(
        airports=a,
        root_origin_code=args.root_origin_code,
        start_not_before=args.start_not_before,
        start_until=args.start_until,
        max_away_days=args.max_away_days,
        min_stay_days=args.min_stay_days,
        cityairports=cityairports,
        unique_country=args.unique_country,
        country_whitelist=country_whitelist,
        blacklist=blacklist,
        max_routes=args.max_routes,
        allowed_starts=allowed_starts,
        sleep=args.sleep,
        session=s,
    )

    print(get_fare.cache_info())
    print(f"found {len(closed_routes)} closed routes, made of {len({f for r in closed_routes for f in r})} flights")
    print(Counter([a[f.destination]["name"] for r in closed_routes for f in r[:-1]]))
    print(Counter([f for r in [{a[f.destination]["country"]["name"] for f in r[:-1]} for r in closed_routes] for f in r]))
    print(Counter([len(r) - 1 for r in closed_routes]))

    for route in sorted(
        closed_routes,
        key=lambda r: sum(f.euro for f in r) / (len(r) - 1),
    ):
        print(
            round(sum(f.euro for f in route) / (len(route) - 1), 2),
            len(route) - 1,
            round(sum(f.euro for f in route), 2),
            route[0].start.strftime("%Y-%m-%d/%H:%M"),
            day_name[route[0].start.weekday()],
            day_name[route[-1].end.weekday()],
            (route[-1].end - route[0].start).days,
            (route[-1].end - route[0].start).seconds // 3600,
            (route[-1].end - route[0].start).seconds // 60 - 60 * ((route[-1].end - route[0].start).seconds // 3600),
            route,
            [(city(f1.destination), str(f2.start - f1.end)) for f1, f2 in zip(route, route[1:])],
            [(f.amount, f.url) for f in route],
        )

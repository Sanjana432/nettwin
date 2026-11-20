"""Compare forwarding under a bounded IPv4 link-state model."""
from dataclasses import dataclass
from heapq import heappop, heappush
from ipaddress import IPv4Address, IPv4Network
import re


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    cost: int

    @property
    def key(self):
        return tuple(sorted((self.a, self.b)))


@dataclass(frozen=True)
class Snapshot:
    routers: tuple[str, ...]
    links: tuple[Link, ...]
    prefixes: dict[str, tuple[IPv4Network, ...]]

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or not {"routers", "links", "prefixes"} <= value.keys():
            raise ValueError("A snapshot needs routers, links and prefixes.")
        routers = value["routers"]
        if not isinstance(routers, list) or not 1 <= len(routers) <= 16:
            raise ValueError("Use one to 16 routers.")
        if any(not isinstance(r, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,15}", r) for r in routers):
            raise ValueError("Router names must be 1–16 letters, digits, hyphens or underscores.")
        if len(set(routers)) != len(routers):
            raise ValueError("Router names must be unique.")
        if not isinstance(value["links"], list) or len(value["links"]) > 40:
            raise ValueError("Use a list of up to 40 links.")
        links = {}
        for row in value["links"]:
            if not isinstance(row, dict) or not {"a", "b", "cost"} <= row.keys():
                raise ValueError("Each link needs a, b and cost.")
            link = Link(row["a"], row["b"], row["cost"])
            if link.a not in routers or link.b not in routers or link.a == link.b:
                raise ValueError("Every link must connect two distinct known routers.")
            if type(link.cost) is not int or not 1 <= link.cost <= 999:
                raise ValueError("Link costs must be integers from 1 to 999.")
            if link.key in links:
                raise ValueError("Duplicate link between " + " and ".join(link.key))
            links[link.key] = link
        prefixes = value["prefixes"]
        if not isinstance(prefixes, dict) or not set(prefixes) <= set(routers):
            raise ValueError("Prefix advertisements must be grouped by known router.")
        parsed = {}
        for router, subnet_list in prefixes.items():
            if not isinstance(subnet_list, list) or len(subnet_list) > 24 or any(not isinstance(p, str) for p in subnet_list):
                raise ValueError("Use a list of up to 24 IPv4 CIDRs per router.")
            parsed[router] = tuple(IPv4Network(p, strict=True) for p in subnet_list)
        return cls(tuple(routers), tuple(links.values()), parsed)


def distances(graph, sources):
    """Multi-source Dijkstra gives minimum cost to any origin."""
    best = {source: 0 for source in sources}
    pending = [(0, source) for source in sorted(sources)]
    while pending:
        cost, router = heappop(pending)
        if cost != best[router]:
            continue
        for neighbor, weight in graph[router]:
            candidate = cost + weight
            if candidate < best.get(neighbor, float("inf")):
                best[neighbor] = candidate
                heappush(pending, (candidate, neighbor))
    return best


class Forwarding:
    def __init__(self, snapshot, failed_link=None):
        self.snapshot = snapshot
        self.graph = {router: [] for router in snapshot.routers}
        for link in snapshot.links:
            if link.key != failed_link:
                self.graph[link.a].append((link.b, link.cost))
                self.graph[link.b].append((link.a, link.cost))
        self._distances = {}

    def routes(self, source, target, via=None):
        """Count all equal-cost branch outcomes and retain bounded example paths."""
        origin_by_prefix = {}
        for router, subnets in self.snapshot.prefixes.items():
            for subnet in subnets:
                if target in subnet:
                    origin_by_prefix.setdefault(subnet, set()).add(router)
        options = sorted(origin_by_prefix.items(), key=lambda item: -item[0].prefixlen)
        tables = []
        for prefix, origins in options:
            key = frozenset(origins)
            if key not in self._distances:
                self._distances[key] = distances(self.graph, origins)
            tables.append((str(prefix), self._distances[key]))

        def route_from(router):
            return next(((prefix, costs) for prefix, costs in tables if router in costs), (None, {}))

        prefix, source_costs = route_from(source)
        if prefix is None:
            return {"prefix": None, "cost": None, "paths": [], "path_count": 0, "paths_via": 0}

        # Because all links are bidirectional, every hop stays in one connected component.
        # The best reachable prefix therefore stays fixed and its distance decreases per hop.
        memo = {}

        def paths_from(router):
            if router in memo:
                return memo[router]
            cost = source_costs[router]
            if cost == 0:
                return 1, int(router == via), [[router]]
            total, passing, examples = 0, 0, []
            for neighbor, weight in sorted(self.graph[router]):
                if source_costs.get(neighbor, float("inf")) + weight != cost:
                    continue
                count, via_count, paths = paths_from(neighbor)
                total += count
                passing += count if router == via else via_count
                examples.extend([router, *path] for path in paths[:max(0, 8-len(examples))])
            memo[router] = total, passing, examples
            return memo[router]

        count, passing, examples = paths_from(source)
        return {"prefix": prefix, "cost": source_costs[source], "paths": examples,
                "path_count": count, "paths_via": passing}


def read_policies(raw, routers):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 24:
        raise ValueError("Provide one to 24 policies.")
    names = set()
    policies = []
    for value in raw:
        if not isinstance(value, dict):
            raise ValueError("Each policy must be an object.")
        name, source, target = (value.get(key) for key in ("name", "source", "target"))
        expect = value.get("expect", "reachable")
        maximum, via = value.get("max_cost"), value.get("via")
        if not isinstance(name, str) or not 1 <= len(name) <= 90 or name in names:
            raise ValueError("Policy names must be unique and 1–90 characters long.")
        if (not isinstance(source, str) or source not in routers
                or (via is not None and (not isinstance(via, str) or via not in routers))):
            raise ValueError("Policy source and via must be known routers in both snapshots.")
        if expect not in ("reachable", "isolated") or not isinstance(target, str):
            raise ValueError("Set an IPv4 destination and a reachable or isolated expectation.")
        if maximum is not None and (type(maximum) is not int or maximum < 1):
            raise ValueError("Policy max_cost must be a positive integer.")
        if expect == "isolated" and (via is not None or maximum is not None):
            raise ValueError("Cost and via constraints require a reachable destination.")
        names.add(name)
        policies.append((name, source, IPv4Address(target), expect, maximum, via))
    return policies


def evaluate(forwarding, policy):
    name, source, target, expect, maximum, via = policy
    route = forwarding.routes(source, target, via)
    reached = bool(route["path_count"])
    if expect == "isolated":
        reason = "An advertised route violates isolation." if reached else ""
    elif not reached:
        reason = "No reachable prefix matches the destination."
    elif maximum is not None and route["cost"] > maximum:
        reason = f"Route cost {route['cost']} exceeds {maximum}."
    elif via is not None and route["paths_via"] != route["path_count"]:
        reason = f"Some equal-cost paths bypass {via}."
    else:
        reason = ""
    return {"name": name, "source": source, "target": str(target), "expect": expect,
            "pass": not reason, "reason": reason, **route}


def compare(baseline, candidate, raw_policies, drill=False):
    before, after = Snapshot.parse(baseline), Snapshot.parse(candidate)
    policies = read_policies(raw_policies, set(before.routers) & set(after.routers))
    engines = Forwarding(before), Forwarding(after)
    rows = []
    for policy in policies:
        old, new = (evaluate(engine, policy) for engine in engines)
        outcome = ("regression" if old["pass"] and not new["pass"] else
                   "fixed" if new["pass"] and not old["pass"] else
                   "unchanged" if old == new else "changed")
        rows.append({"name": policy[0], "before": old, "after": new, "outcome": outcome})
    failures = []
    if drill:
        passing = [policy for policy, row in zip(policies, rows) if row["after"]["pass"]]
        for link in after.links:
            engine = Forwarding(after, link.key)
            broken = [row["name"] for row in (evaluate(engine, p) for p in passing) if not row["pass"]]
            failures.append({"link": list(link.key), "violations": broken})
    old_links = {link.key: link.cost for link in before.links}
    new_links = {link.key: link.cost for link in after.links}
    changes = [{"link": list(key), "before": old_links.get(key), "after": new_links.get(key)}
               for key in sorted(old_links.keys() | new_links.keys()) if old_links.get(key) != new_links.get(key)]
    prefix_changes = [{"router": router, "before": old, "after": new}
                      for router in sorted(set(before.routers) | set(after.routers))
                      if (old := sorted(map(str, before.prefixes.get(router, ())))) !=
                         (new := sorted(map(str, after.prefixes.get(router, ()))))]
    return {"policies": rows, "link_changes": changes, "prefix_changes": prefix_changes,
            "failures": failures, "passed": all(row["after"]["pass"] for row in rows)}

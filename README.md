# NetTwin

NetTwin simulates the effect of an IPv4 routing change before a rollout. Compare baseline and candidate snapshots, inspect equal-cost paths, and run one outage per candidate link to find policies that would fail.

## Run it

Requires Python 3.11 or newer. Run these commands from this repository.

```console
python -m pip install -e ".[test]"
python -m nettwin serve
```

Open [the NetTwin dashboard](http://127.0.0.1:8131). It starts with a route withdrawal. Select **Before** to see two equal-cost paths from Access to Core, then select **After** to see the route disappear. Switch to **Raise an uplink cost** to see a healthy candidate lose one equal-cost path at steady state. In the failure drill, losing the remaining cheapest uplink pushes the traffic over its cost budget. **Connect the guest network** shows an isolation violation.

## Use your own data

Open **Compare your own snapshots** for editable JSON, or run the CLI. Each snapshot lists router names, bidirectional links with positive integer costs, and CIDRs advertised by each router. Each policy supplies a name, source router, and destination IPv4 address. Optional keys include `expect` (`reachable` or `isolated`), `max_cost`, and `via` (a router required on every shortest path).

```console
python -m nettwin demo cost --drill
python -m nettwin demo withdraw --drill
python -m nettwin check topology.json --drill
python -m unittest discover -s tests -v
```

`demo` and `check` print JSON and return exit code 1 if any steady-state candidate policy fails. The outage drill reports violations introduced by each link failure. The dashboard can also export the report.

## Forwarding model

1. For each matching prefix, use multi-source Dijkstra to find the minimum cost to its advertising routers. Use the longest prefix reachable from the traffic source.
2. Follow edges whose costs preserve that minimum. Positive weights make this path graph acyclic. Count all equal-cost paths and retain up to eight examples.
3. Compare reachability, cost, isolation, and waypoint policies across snapshots. Recompute forwarding for each single-link failure when requested.

The model uses static IPv4 advertisements and converged link-state routing over symmetric links. It does not model BGP, ACLs, routing convergence, or vendor configurations. The web API accepts up to 16 routers, 40 links and 24 policies per comparison.

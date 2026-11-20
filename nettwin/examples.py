from copy import deepcopy


def scenario(name="withdraw"):
    baseline = {
        "routers": ["Access", "East", "West", "Core", "Guest", "Lab"],
        "links": [
            {"a": "Access", "b": "East", "cost": 10},
            {"a": "Access", "b": "West", "cost": 10},
            {"a": "East", "b": "Core", "cost": 10},
            {"a": "West", "b": "Core", "cost": 10},
            {"a": "Guest", "b": "Lab", "cost": 5},
        ],
        "prefixes": {"Core": ["10.20.0.0/24"], "Lab": ["10.40.0.0/24"]},
    }
    candidate = deepcopy(baseline)
    if name == "withdraw":
        candidate["prefixes"]["Core"] = []
    elif name == "cost":
        candidate["links"][0]["cost"] = 25
    elif name == "isolation":
        candidate["links"].append({"a": "Guest", "b": "Access", "cost": 6})
    elif name != "unchanged":
        raise ValueError("Unknown scenario.")
    policies = [
        {"name": "Access reaches service", "source": "Access", "target": "10.20.0.8", "max_cost": 25},
        {"name": "Guest stays separate from service", "source": "Guest", "target": "10.20.0.8", "expect": "isolated"},
        {"name": "Guest reaches its lab", "source": "Guest", "target": "10.40.0.8"},
    ]
    return {"baseline": baseline, "candidate": candidate, "policies": policies}

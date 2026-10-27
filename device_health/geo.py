from math import radians, cos, sin, asin, sqrt


def haversine(L1, L2):
    """Great-circle distance in metres between two [lon, lat] points.

    Same function used across the original notebooks.
    """
    try:
        lon1, lat1 = L1[0], L1[1]
        lon2, lat2 = L2[0], L2[1]
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        r = 6371000  # earth radius in metres
        return c * r
    except Exception:
        return None

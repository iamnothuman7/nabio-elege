import math

from django.core.exceptions import ValidationError


def validate_boundary(value):
    if not value:
        return
    message = "Use um polígono simples com 3 a 200 vértices, sem cruzamentos, em coordenadas GeoJSON."
    if (
        not isinstance(value, dict)
        or set(value) != {"type", "coordinates"}
        or value["type"] != "Polygon"
    ):
        raise ValidationError(message)
    coordinates = value["coordinates"]
    if not isinstance(coordinates, list) or len(coordinates) != 1:
        raise ValidationError(message)
    ring = coordinates[0]
    if not isinstance(ring, list) or not 4 <= len(ring) <= 201 or ring[0] != ring[-1]:
        raise ValidationError(message)
    for point in ring:
        if (
            not isinstance(point, list)
            or len(point) != 2
            or any(
                isinstance(number, bool)
                or not isinstance(number, (float, int))
                or not math.isfinite(number)
                for number in point
            )
        ):
            raise ValidationError(message)
        if not -180 <= point[0] <= 180 or not -85 <= point[1] <= 85:
            raise ValidationError(message)
    if len({tuple(point) for point in ring[:-1]}) != len(ring) - 1:
        raise ValidationError(message)
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
    if abs(area) < 1e-12:
        raise ValidationError(message)

    def orientation(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def between(a, b, c):
        return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[
            1
        ] <= max(a[1], b[1])

    edges = list(zip(ring, ring[1:]))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 2, len(edges)):
            if i == 0 and j == len(edges) - 1:
                continue
            c, d = edges[j]
            values = (
                orientation(a, b, c),
                orientation(a, b, d),
                orientation(c, d, a),
                orientation(c, d, b),
            )
            if values[0] * values[1] < 0 and values[2] * values[3] < 0:
                raise ValidationError(message)
            if any(
                abs(o) < 1e-12 and between(x, y, z)
                for o, x, y, z in (
                    (values[0], a, b, c),
                    (values[1], a, b, d),
                    (values[2], c, d, a),
                    (values[3], c, d, b),
                )
            ):
                raise ValidationError(message)

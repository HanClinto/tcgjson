from tcgjson.tcgplayer import TCGplayerClient


class JsonResponse:
    status_code = 200
    headers = {"content-type": "application/json"}
    url = "https://example.test/data"

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class CountingSession:
    def __init__(self):
        self.headers = {}
        self.calls = 0

    def request(self, method, url, timeout=None, **kwargs):
        self.calls += 1
        return JsonResponse([{"productLineId": 1, "productLineName": "Magic"}])


def test_request_cache_reuses_cached_json_payload(tmp_path) -> None:
    session = CountingSession()
    client = TCGplayerClient(session=session, request_cache_dir=tmp_path)

    assert client.get_product_lines() == [{"productLineId": 1, "productLineName": "Magic"}]
    assert client.get_product_lines() == [{"productLineId": 1, "productLineName": "Magic"}]

    assert session.calls == 1
    assert client.stats().requests == 1
    assert client.stats().cache_hits == 1
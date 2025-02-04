from cloudevents.conversion import to_structured
from cloudevents.http import CloudEvent
from requests import post as req_post

URL: str = "http://localhost:8080/"
attributes: dict[str, str] = {
    "Content-Type": "application/json",
    "source": "testing",
    "type": "testing",
}
data: str = "testing"

req_post(
    URL, **dict(zip(("headers", "data"), to_structured(CloudEvent(attributes, data))))
)

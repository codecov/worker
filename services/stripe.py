import stripe
from shared.config import get_config

stripe.api_key = get_config("services", "stripe", "api_key")
stripe.api_version = "2024-12-18.acacia"

client = stripe.http_client.RequestsClient()
stripe.default_http_client = client

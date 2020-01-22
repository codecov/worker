import stripe

from covreports.config import get_config

stripe.api_key = get_config('services', 'stripe', 'api_key')

client = stripe.http_client.RequestsClient()
stripe.default_http_client = client

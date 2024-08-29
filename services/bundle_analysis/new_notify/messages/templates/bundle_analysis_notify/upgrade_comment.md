The author of this PR, {{author_username}}, {% if codecov_instance == "cloud" %}is not an activated member of this organization on Codecov.{% else %}is not activated in your Codecov Self-Hosted installation.{% endif %}
Please [activate this user]({{activation_link}}) to display this PR comment.
Bundle data is still being uploaded to {{codecov_name}} for purposes of overall calculations.
{% if codecov_instance == "cloud" %}
Please don't hesitate to email us at support@codecov.io with any questions.
{% else %}
Please contact your Codecov On-Premises installation administrator with any questions.
{% endif %}
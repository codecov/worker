## [Bundle]({{pull_url}}) Report
{% if total_size_delta == 0 %}
Bundle size has no change :white_check_mark:
{% else %}
{% if status_level == "ERROR" %}:x: Check failed: c{% else %}C{% endif %}hanges will {% if total_size_delta > 0 %}increase{% else %}decrease{% endif %} total bundle size by {{total_size_readable}} ({{total_percentage}}) {% if total_size_delta > 0 %}:arrow_up:{% else %}:arrow_down:{% endif %}{% if status_level == "WARNING" %}:warning:, exceeding the [configured](https://docs.codecov.com/docs/javascript-bundle-analysis#main-features) threshold of {{warning_threshold_readable}}.{% elif status_level == "ERROR" %}, **exceeding** the [configured](https://docs.codecov.com/docs/javascript-bundle-analysis#main-features) threshold of {{warning_threshold_readable}}.{% else %}. This is within the [configured](https://docs.codecov.com/docs/javascript-bundle-analysis#main-features) threshold :white_check_mark:{% endif %}
{% endif %}
{% if bundle_rows %}{% include "bundle_analysis_notify/bundle_table.md" %}{% if has_cached %}

ℹ️ *Bundle size includes cached data from a previous commit
{%endif%}{% endif %}
{% if bundle_route_data %}{% include "bundle_analysis_notify/bundle_route_table.md" %}{% endif %}
## [Bundle]({{pull_url}}) Report
{% if total_size_delta == 0 %}
Bundle size has no change :white_check_mark:
{% elif total_size_delta > 0 %}
Changes will increase total bundle size by {{total_size_readable}} :arrow_up:
{% else %}
Changes will decrease total bundle size by {{total_size_readable}} :arrow_down:
{% endif %}
{% include "bundle_analysis_notify/bundle_table.md" %}
| Bundle name | Size | Change |
| ----------- | ---- | ------ |{% for bundle_row in bundle_rows %}
| {{bundle_row.bundle_name}}{% if bundle_row.is_cached %}*{% endif %} | {{bundle_row.bundle_size}} | {{bundle_row.change_size_readable}} {{bundle_row.change_icon}} |{% endfor %}

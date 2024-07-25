
| Bundle name | Size | Change |
| ----------- | ---- | ------ |
{% for bundle_row in bundle_rows_list %}
| {bundle_row.bundle_name} | {bundle_row.size} | {bundle_row.change_readable} {bundle_row.change_icon} |
{% endfor %}
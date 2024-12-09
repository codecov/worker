{% for bundle_name, routes in bundle_route_data.items %}
<details>
  <summary>View changes by path for bundle: {{ bundle_name }}</summary>

| File path | Size | Change |
| --------- | ---- | ------ |{% for bundle_route_row in routes %}
| {{bundle_route_row.route_name}} | {{bundle_route_row.route_size}} | {{bundle_route_row.change_size_readable}} ({{bundle_route_row.percentage_change_readable}}) {{bundle_route_row.change_icon}}{{bundle_route_row.}} |{% endfor %}

</details>
{% endfor %}

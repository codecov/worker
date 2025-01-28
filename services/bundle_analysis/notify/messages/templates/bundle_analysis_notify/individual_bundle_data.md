
### Affected Assets, Files, and Routes:
{% for bundle_name, bundle_data in individual_bundle_data.items %}
<details>
<summary>view changes for bundle: {{ bundle_name }}</summary>

{% if bundle_data.asset_data %}#### **Assets Changed:**
| Asset Name | Size Change | Total Size | Change (%) |
| ---------- | ----------- | ---------- | ---------- |{% for row in bundle_data.asset_data %}
| {{row.asset_display_name_1}} | {{row.change_size_readable}} | {{row.asset_size_readable}} | {{row.percentage_change_readable}} {{row.change_icon}} |{% endfor %}

{% for row in bundle_data.asset_data %}
{% if row.module_data %}**Files in** {{row.asset_display_name_2}}:
{% for module in row.module_data %}
- {{module.module_name}} → Total Size: **{{module.change_size_readable}}**
{% endfor %}
{% endif %}
{% endfor %}
{% endif %}
{% if bundle_data.app_routes_data %}#### App Routes Affected:

| App Route | Size Change | Total Size | Change (%) |
| --------- | ----------- | ---------- | ---------- |{% for row in bundle_data.app_routes_data %}
| {{row.route_name}} | {{row.change_size_readable}} | {{row.route_size}} | {{row.percentage_change_readable}} {{row.change_icon}} |{% endfor %}

{% endif %}
</details>
{% endfor %}
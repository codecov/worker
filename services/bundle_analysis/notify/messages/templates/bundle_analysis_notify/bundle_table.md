{% if status_level == "INFO" %}<details><summary>Detailed changes</summary>

{% endif %}| Bundle name | Size | Change |
| ----------- | ---- | ------ |{% for bundle_row in bundle_rows %}
| {{bundle_row.bundle_name}}{% if bundle_row.is_cached %}*{% endif %} | {{bundle_row.bundle_size}} | {{bundle_row.change_size_readable}} ({{bundle_row.percentage_change_readable}}) {{bundle_row.change_icon}}{% if bundle_row.is_change_outside_threshold and status_level == "WARNING" %}:warning:{% elif bundle_row.is_change_outside_threshold and status_level == "ERROR"%}:x:{% endif %}{{bundle_row.}} |{% endfor %}{% if status_level == "INFO" %}

</details>{% endif %}
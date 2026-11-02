{{ objname | escape | underline }}

.. currentmodule:: {{ module }}

.. auto{{ objtype }}:: {{ objname }}
{% if objtype == "data" %}   :no-value:
{% endif %}

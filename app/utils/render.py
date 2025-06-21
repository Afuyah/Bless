
from flask import render_template, request

def render_htmx(template_fragment, **context):
    if request.headers.get("HX-Request") == "true":
        # HTMX request: return only the fragment
        return render_template(template_fragment, **context)
    else:
        # Full request: inject the fragment inside the full dashboard shell
        return render_template(
            "auth/admin_dashboard.html",
            fragment_template=template_fragment,
            **context
        )

        

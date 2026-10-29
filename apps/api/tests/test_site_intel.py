"""Reading a site's own code before touching it.

The suite proves the three decisions the batch depends on:

* what the site is (platform from the resources it really loaded),
* where its sign-up is (links, scripts, platform defaults) without guessing,
* whether a public form already accepts a link (no account needed).
"""

from __future__ import annotations

from app.services import site_intel


def _page(**overrides) -> dict:
    data = {
        "url": "https://directory.example.org/",
        "title": "Example directory",
        "generator": "",
        "lang": "en",
        "forms": [],
        "links": [],
        "buttons": [],
        "scripts": [],
        "inline": "",
        "resources": [],
        "bodyText": "",
    }
    data.update(overrides)
    return data


def _link(text: str, href: str) -> dict:
    return {"text": text, "href": href}


def test_wordpress_is_recognised_from_the_loaded_resources() -> None:
    data = _page(
        resources=[
            "https://directory.example.org/wp-content/themes/x/style.css",
            "https://directory.example.org/wp-includes/js/jquery.js",
        ],
        links=[_link("Sign up", "https://directory.example.org/wp-login.php?action=register")],
    )
    intel = site_intel.analyze(data)
    assert intel["platform"] == "wordpress"
    assert "wp-content" in intel["platform_evidence"]
    assert intel["plan"] == "SIGNUP"
    assert intel["signup_urls"][0].endswith("wp-login.php?action=register")


def test_a_signup_link_in_another_language_is_found() -> None:
    data = _page(
        links=[
            _link("Iniciar sesión", "https://directory.example.org/login"),
            _link("Crear cuenta", "https://directory.example.org/es/registro"),
        ]
    )
    intel = site_intel.analyze(data)
    assert "https://directory.example.org/es/registro" in intel["signup_urls"]
    assert "https://directory.example.org/login" not in intel["signup_urls"]


def test_a_route_from_the_site_javascript_is_used() -> None:
    data = _page()
    script = 'const routes = {home: "/", registerPath: "/account/create", about: "/about"};'
    intel = site_intel.analyze(data, script_text=script)
    assert "https://directory.example.org/account/create" in intel["signup_urls"]


def test_a_comment_form_with_a_url_field_needs_no_account() -> None:
    data = _page(
        url="https://blog.example.org/post/hello",
        forms=[
            {
                "action": "https://blog.example.org/post/hello",
                "method": "post",
                "id": "commentform",
                "cls": "comment-form",
                "fields": [
                    {"name": "author", "type": "text", "placeholder": "Name"},
                    {"name": "email", "type": "email", "placeholder": "E-mail"},
                    {"name": "url", "type": "url", "placeholder": "Website"},
                    {"name": "comment", "type": "textarea", "placeholder": ""},
                ],
            }
        ],
    )
    intel = site_intel.analyze(data)
    assert intel["direct"] is not None
    assert intel["direct"]["kind"] == "comment form"
    assert intel["direct"]["fields"] == ["url"]
    # No sign-up link anywhere -> the public form is the plan.
    assert intel["plan"] == "DIRECT"


def test_a_login_wall_never_counts_as_a_public_form() -> None:
    data = _page(
        bodyText="You must be logged in to post a comment.",
        forms=[
            {
                "action": "https://blog.example.org/post/hello",
                "method": "post",
                "id": "commentform",
                "cls": "",
                "fields": [{"name": "url", "type": "url", "placeholder": "Website"}],
            }
        ],
    )
    intel = site_intel.analyze(data)
    assert intel["direct"] is None
    assert intel["plan"] == "NONE"


def test_a_newsletter_form_is_not_a_public_link_form() -> None:
    data = _page(
        forms=[
            {
                "action": "https://directory.example.org/newsletter",
                "method": "post",
                "id": "newsletter",
                "cls": "",
                "fields": [{"name": "url", "type": "url", "placeholder": "Website"}],
            }
        ]
    )
    assert site_intel.analyze(data)["direct"] is None


def test_a_signup_is_preferred_over_a_public_form() -> None:
    data = _page(
        links=[_link("Register", "https://directory.example.org/register")],
        forms=[
            {
                "action": "https://directory.example.org/submit",
                "method": "post",
                "id": "submit",
                "cls": "",
                "fields": [{"name": "website", "type": "text", "placeholder": "Website"}],
            }
        ],
    )
    intel = site_intel.analyze(data)
    assert intel["plan"] == "SIGNUP"
    assert intel["direct"] is not None


def test_login_only_sites_report_a_login_plan() -> None:
    data = _page(
        forms=[
            {
                "action": "https://directory.example.org/session",
                "method": "post",
                "id": "login",
                "cls": "",
                "fields": [
                    {"name": "email", "type": "email", "placeholder": "E-mail"},
                    {"name": "password", "type": "password", "placeholder": "Password"},
                ],
            }
        ]
    )
    intel = site_intel.analyze(data)
    assert intel["plan"] == "LOGIN"
    assert intel["login_urls"][0] == "https://directory.example.org/session"


def test_the_brief_is_small_and_useful() -> None:
    data = _page(
        resources=["https://directory.example.org/wp-content/x.css"],
        links=[_link("Sign up", "https://directory.example.org/wp-login.php?action=register")],
    )
    brief = site_intel.brief(site_intel.analyze(data))
    assert brief["platform"] == "wordpress"
    assert brief["plan"] == "SIGNUP"
    assert len(brief["signup_urls"]) <= 6
    assert brief["direct"] is None


def test_inspect_reads_the_page_and_its_own_javascript() -> None:
    snapshot = _page(
        url="https://directory.example.org/",
        links=[_link("Sign up", "https://directory.example.org/join")],
        scripts=[
            "https://directory.example.org/app.js",
            "https://cdn.example.net/vendor.js",
        ],
    )

    class Page:
        def evaluate(self, script, arg=None):
            if arg is None:
                return snapshot
            # Only the site's own bundle may be fetched.
            assert arg == ["https://directory.example.org/app.js"]
            return 'signupUrl: "/join-now"'

    intel = site_intel.inspect(Page())
    assert intel["plan"] == "SIGNUP"
    assert "https://directory.example.org/join-now" in intel["signup_urls"]


def test_explain_names_the_reason_instead_of_guessing() -> None:
    intel = site_intel.analyze(
        _page(resources=["https://directory.example.org/wp-content/x.css"])
    )
    text = site_intel.explain(intel)
    assert "WordPress" in text
    assert site_intel.label(intel) == "WordPress"


def test_continue_with_google_is_detected_and_preferred() -> None:
    data = _page(
        links=[_link("Register", "https://directory.example.org/register")],
        buttons=[{"text": "Continue with Google", "type": "button"}],
    )
    intel = site_intel.analyze(data)
    assert intel["oauth"][0]["provider"] == "google"
    assert intel["oauth"][0]["how"] == "button"
    # Google reuses the project session: no password, no code.
    assert intel["plan"] == "GOOGLE"


def test_google_inside_an_oauth_iframe_is_detected() -> None:
    data = _page(
        url="https://directory.example.org/signup",
        iframes=["https://accounts.google.com/gsi/button?client_id=x"],
    )
    intel = site_intel.analyze(data)
    assert [item["provider"] for item in intel["oauth"]] == ["google"]
    assert intel["plan"] == "GOOGLE"


def test_other_providers_do_not_override_a_password_signup() -> None:
    data = _page(
        links=[
            _link("Sign up", "https://directory.example.org/register"),
            _link("Continue with Facebook", "https://www.facebook.com/dialog/oauth?client_id=1"),
        ]
    )
    intel = site_intel.analyze(data)
    assert {item["provider"] for item in intel["oauth"]} == {"facebook"}
    assert intel["plan"] == "SIGNUP"


def test_internal_pages_are_ranked_for_the_backlink() -> None:
    data = _page(
        links=[
            _link("Login", "https://directory.example.org/login"),
            _link("Forum", "https://directory.example.org/forum"),
            _link("Submit a listing", "https://directory.example.org/add-listing"),
            _link("Edit profile", "https://directory.example.org/profile/edit"),
            _link("Write a post", "https://directory.example.org/blog/write"),
        ]
    )
    urls = site_intel.analyze(data)["backlink_urls"]
    assert urls[0].endswith("/profile/edit")
    assert any(url.endswith("/add-listing") for url in urls)
    assert not any("/login" in url for url in urls)


def test_the_csv_site_check_says_what_was_seen_and_left_empty() -> None:
    from app.api.routes.backlink_campaign import _site_check

    cell = _site_check(
        {
            "platform": "wordpress",
            "plan": "SIGNUP",
            "fields": {"skipped": [{"field": "coupon_code", "why": "left alone"}]},
        }
    )
    assert "wordpress" in cell
    assert "plan SIGNUP" in cell
    assert "coupon_code" in cell

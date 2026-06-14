import reflex as rx

config = rx.Config(
    app_name="ai_orbit_solar_power_plant",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)
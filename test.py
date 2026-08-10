from pathlib import Path

import matplotlib.pyplot as plt
import requests
from tqdm import tqdm
from pyrosm import OSM


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

DATA_DIR = Path("data")

PBF_URL = (
    "https://download.geofabrik.de/"
    "europe/germany/schleswig-holstein-latest.osm.pbf"
)

PBF_FILE = DATA_DIR / "schleswig-holstein-latest.osm.pbf"

FORCE_DOWNLOAD = False

# Beschriftungen kleinerer Städte anzeigen
LABEL_TOWNS = True


# ----------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------

def download_file(url: str, target: Path, force: bool = False):

    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and not force:
        print(f"Using existing file: {target}")
        return

    temp_file = target.with_suffix(target.suffix + ".part")

    print(f"Downloading:")
    print(f"  {url}")
    print(f"to:")
    print(f"  {target}")

    with requests.get(
        url,
        stream=True,
        timeout=(10, 120),
    ) as response:

        response.raise_for_status()

        total_size = int(
            response.headers.get("content-length", 0)
        )

        with open(temp_file, "wb") as f:

            with tqdm(
                total=total_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc="Download",
            ) as progress:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if not chunk:
                        continue

                    f.write(chunk)
                    progress.update(len(chunk))

    temp_file.replace(target)

    print("Download finished.")


# ----------------------------------------------------------------------
# Roads
# ----------------------------------------------------------------------

def load_road_network(osm: OSM):

    print()
    print("Extracting road network ...")

    roads = osm.get_network(
        network_type="driving"
    )

    print(f"Road segments: {len(roads):,}")

    return roads


# ----------------------------------------------------------------------
# Cities / towns
# ----------------------------------------------------------------------

def load_cities(osm: OSM):
    """
    Read city and town centre nodes from OSM.

    place=city : larger cities
    place=town : smaller cities / towns
    """

    print()
    print("Extracting cities and towns ...")

    cities = osm.get_data_by_custom_criteria(
        custom_filter={
            "place": [
                "city",
                "town",
            ]
        },

        # Explicitly request OSM tags as dataframe columns
        tags_as_columns=[
            "name",
            "place",
            "population",
        ],

        keep_nodes=True,
        keep_ways=False,
        keep_relations=False,
    )

    print("Columns:")
    print(cities.columns.tolist())

    if cities.empty:
        print("No cities/towns found.")
        return cities

    # Remove objects without names
    cities = cities[
        cities["name"].notna()
    ].copy()

    print(f"Cities/towns: {len(cities):,}")

    return cities


# ----------------------------------------------------------------------
# Administrative boundaries
# ----------------------------------------------------------------------

def load_municipal_boundaries(osm: OSM):

    print()
    print("Extracting municipal boundaries ...")

    boundaries = osm.get_boundaries(
        boundary_type="administrative",

        custom_filter={
            "admin_level": ["8"]
        },

        extra_attributes=[
            "place",
            "de:amtlicher_gemeindeschluessel",
        ],
    )

    # Keep only named areas
    boundaries = boundaries[
        boundaries["name"].notna()
    ].copy()

    print(
        f"Municipal boundaries "
        f"(admin_level=8): {len(boundaries):,}"
    )

    return boundaries


# ----------------------------------------------------------------------
# Plot
# ----------------------------------------------------------------------

def plot_map(
    roads,
    cities,
    boundaries,
):

    # --------------------------------------------------------------
    # Project everything to ETRS89 / UTM 32N
    # --------------------------------------------------------------

    roads = roads.to_crs(epsg=25832)
    cities = cities.to_crs(epsg=25832)
    boundaries = boundaries.to_crs(epsg=25832)

    major_cities = cities[
        cities["place"] == "city"
    ]

    towns = cities[
        cities["place"] == "town"
    ]

    print()
    print(f"place=city: {len(major_cities)}")
    print(f"place=town: {len(towns)}")
    print(f"Municipalities: {len(boundaries)}")

    # --------------------------------------------------------------
    # Figure
    # --------------------------------------------------------------

    fig, ax = plt.subplots(
        figsize=(10, 12)
    )

    # --------------------------------------------------------------
    # Administrative boundaries
    # --------------------------------------------------------------

    boundaries.plot(
        ax=ax,
        facecolor="none",
        edgecolor="black",
        linewidth=0.4,
        alpha=0.5,
        zorder=1,
    )

    # --------------------------------------------------------------
    # Roads
    # --------------------------------------------------------------

    roads.plot(
        ax=ax,
        linewidth=0.3,
        color="gray",
        alpha=0.8,
        zorder=2,
    )

    # --------------------------------------------------------------
    # Towns
    # --------------------------------------------------------------

    towns.plot(
        ax=ax,
        marker="o",
        markersize=10,
        color="orange",
        zorder=3,
        label="Town",
    )

    # --------------------------------------------------------------
    # Cities
    # --------------------------------------------------------------

    major_cities.plot(
        ax=ax,
        marker="o",
        markersize=35,
        color="red",
        zorder=4,
        label="City",
    )

    # --------------------------------------------------------------
    # Labels for major cities
    # --------------------------------------------------------------

    for _, row in major_cities.iterrows():

        ax.annotate(
            row["name"],
            xy=(
                row.geometry.x,
                row.geometry.y,
            ),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=9,
            fontweight="bold",
            zorder=5,
        )

    # --------------------------------------------------------------
    # Labels for towns
    # --------------------------------------------------------------

    if LABEL_TOWNS:

        for _, row in towns.iterrows():

            ax.annotate(
                row["name"],
                xy=(
                    row.geometry.x,
                    row.geometry.y,
                ),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=6,
                zorder=5,
            )

    # --------------------------------------------------------------
    # Formatting
    # --------------------------------------------------------------

    ax.set_title(
        "OpenStreetMap\n"
        "Road network, cities and municipalities "
        "of Schleswig-Holstein",
        fontsize=14,
    )

    ax.set_aspect("equal")
    ax.axis("off")

    ax.legend(
        loc="lower right"
    )

    plt.tight_layout()
    plt.show()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():

    # --------------------------------------------------------------
    # Download
    # --------------------------------------------------------------

    download_file(
        PBF_URL,
        PBF_FILE,
        force=FORCE_DOWNLOAD,
    )

    # --------------------------------------------------------------
    # Open OSM file
    # --------------------------------------------------------------

    print()
    print("Opening PBF file ...")

    osm = OSM(
        str(PBF_FILE)
    )

    # --------------------------------------------------------------
    # Extract data
    # --------------------------------------------------------------

    roads = load_road_network(
        osm
    )

    cities = load_cities(
        osm
    )

    boundaries = load_municipal_boundaries(
        osm
    )

    # --------------------------------------------------------------
    # Information
    # --------------------------------------------------------------

    print()
    print("Municipal boundaries:")

    available_columns = [
        column
        for column in [
            "name",
            "admin_level",
            "place",
            "de:amtlicher_gemeindeschluessel",
        ]
        if column in boundaries.columns
    ]

    print(
        boundaries[
            available_columns
        ]
        .sort_values("name")
        .to_string(index=False)
    )

    # --------------------------------------------------------------
    # Plot
    # --------------------------------------------------------------

    plot_map(
        roads,
        cities,
        boundaries,
    )


if __name__ == "__main__":
    main()
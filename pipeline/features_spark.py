"""
PySpark job: build pre match form features from raw football-data.co.uk CSVs.

For every match, each team gets features computed from its previous N matches
only (rows between -N and -1 in a date ordered window), so nothing from the
match itself or later leaks into the features. Windows run across seasons, so
early season form uses the end of the previous season.

Run locally:
    python pipeline/features_spark.py
Output: data/features/features.csv (one row per match with enough history).
"""

import glob
import os
import sys

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

N = 5  # matches of history per team
RAW_GLOB = os.path.join("data", "raw", "E0_*.csv")
OUT_DIR = os.path.join("data", "features")


def season_from_path(path):
    code = os.path.basename(path).split("_")[1].split(".")[0]  # e.g. 2122
    return f"20{code[:2]}/{code[2:]}"


def load_matches(spark):
    parts = []
    for p in sorted(glob.glob(RAW_GLOB)):
        df = (
            spark.read.option("header", True).csv(p)
            .select("Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR")
            .withColumn("season", F.lit(season_from_path(p)))
        )
        parts.append(df)
    if not parts:
        sys.exit(f"No files match {RAW_GLOB}")
    df = parts[0]
    for d in parts[1:]:
        df = df.unionByName(d)
    df = (
        df.where(F.col("FTR").isNotNull() & (F.col("HomeTeam") != ""))
        .withColumn("date", F.to_date("Date", "dd/MM/yyyy"))
        .withColumn("hg", F.col("FTHG").cast("int"))
        .withColumn("ag", F.col("FTAG").cast("int"))
        .withColumn("match_id", F.monotonically_increasing_id())
        .select("match_id", "season", "date", "HomeTeam", "AwayTeam", "hg", "ag", "FTR")
    )
    return df


def team_rows(matches):
    """Long format: one row per team per match."""
    home = matches.select(
        "match_id", "season", "date",
        F.col("HomeTeam").alias("team"),
        F.col("hg").alias("gf"), F.col("ag").alias("ga"),
        F.when(F.col("FTR") == "H", 3).when(F.col("FTR") == "D", 1).otherwise(0).alias("pts"),
    )
    away = matches.select(
        "match_id", "season", "date",
        F.col("AwayTeam").alias("team"),
        F.col("ag").alias("gf"), F.col("hg").alias("ga"),
        F.when(F.col("FTR") == "A", 3).when(F.col("FTR") == "D", 1).otherwise(0).alias("pts"),
    )
    return home.unionByName(away)


def add_form(rows):
    w = Window.partitionBy("team").orderBy("date", "match_id").rowsBetween(-N, -1)
    return (
        rows.withColumn("n_prev", F.count("pts").over(w))
        .withColumn("form_ppg", F.avg("pts").over(w))
        .withColumn("form_gf", F.avg("gf").over(w))
        .withColumn("form_ga", F.avg("ga").over(w))
        .withColumn("form_gd", F.col("form_gf") - F.col("form_ga"))
    )


def build_features(spark):
    matches = load_matches(spark)
    form = add_form(team_rows(matches))
    cols = ["match_id", "n_prev", "form_ppg", "form_gf", "form_ga", "form_gd"]
    # each team appears once per match, so pick the home and away rows by team
    h = form.join(matches.select("match_id", "HomeTeam"), "match_id").where(
        F.col("team") == F.col("HomeTeam")
    ).select("match_id", *[F.col(c).alias("h_" + c) for c in cols[1:]])
    a = form.join(matches.select("match_id", "AwayTeam"), "match_id").where(
        F.col("team") == F.col("AwayTeam")
    ).select("match_id", *[F.col(c).alias("a_" + c) for c in cols[1:]])
    out = (
        matches.join(h, "match_id").join(a, "match_id")
        .where((F.col("h_n_prev") == N) & (F.col("a_n_prev") == N))
        .withColumn("d_ppg", F.col("h_form_ppg") - F.col("a_form_ppg"))
        .withColumn("d_gd", F.col("h_form_gd") - F.col("a_form_gd"))
        .orderBy("date", "match_id")
    )
    return out


def main():
    spark = (
        SparkSession.builder.master("local[2]").appName("pl-form-features")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    feats = build_features(spark)
    pdf = feats.toPandas()  # ~3000 rows
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "features.csv")
    pdf = pdf.drop(columns=["match_id"])
    pdf.to_csv(out, index=False)
    print(f"Wrote {len(pdf)} matches to {out}")
    spark.stop()


if __name__ == "__main__":
    main()

import shutil
import sys
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import requests

from trainer.logger import get_logger

logger = get_logger(__name__)


def download_data(url="http://mattmahoney.net/dc/text8.zip", dest_dir="data"):
    # prepare destination
    dest = Path(dest_dir) / Path(url).name
    dest.parent.mkdir(parents=True, exist_ok=True)

    # downlaod zip
    if not dest.exists():
        logger.info("downloading file: %s.", url)
        r = requests.get(url, stream=True)
        with dest.open("wb") as f:
            shutil.copyfileobj(r.raw, f)
        logger.info("file downloaded: %s.", dest)

    # extract zip
    if not Path(dest_dir, "text8").exists():
        with dest.open("rb") as f, ZipFile(f, "r") as zf:
            zf.extractall(dest_dir)
        logger.info("file extracted.")


def load_data(src_dir="data"):
    file_path = Path(src_dir, "text8")
    with open(file_path) as f:
        text8 = f.read()
    logger.info("file loaded: %s.", file_path)
    return text8


def process_data(text8, vocab_size=None, coverage=0.9, context_size=5):
    text8_tokens = text8.split()

    # create vocab
    df_vocab = create_vocabulary(text8_tokens, vocab_size, coverage)
    vocab_size, _ = df_vocab.shape
    logger.info("vocab created, size: %s.", vocab_size)

    # compute interaction
    df_interaction = create_interaction_dataframe(text8_tokens, df_vocab, context_size)
    df_interaction = create_glove_dataframe(df_interaction)

    return {"vocabulary": df_vocab, "interaction": df_interaction}


def create_vocabulary(text_tokens, vocab_size=None, coverage=0.9):
    tokens_counter = Counter(text_tokens)

    # find cumulative proportion of token counts
    counts = np.sort(list(tokens_counter.values()))[::-1]
    total = np.sum(counts)
    counts_cumprop = np.cumsum(counts) / total

    # get count with defined coverage of total tokens
    count_cutoff = counts[np.searchsorted(counts_cumprop, coverage)]
    logger.info("count cufoff: %s; token coverage: %s.", count_cutoff, coverage)

    # get vocab and counts
    vocab = [token for token, count in tokens_counter.most_common(vocab_size) if count >= count_cutoff]
    vocab_counts = [tokens_counter[token] for token in vocab]
    unk_count = total - np.sum(vocab_counts)

    df_vocab = pd.DataFrame({"token": ["<UNK>"] + vocab, "count": [unk_count] + vocab_counts})
    df_vocab["proportion"] = df_vocab["count"] / total
    df_vocab = df_vocab.sort_values("count", ascending=False).reset_index(drop=True)
    return df_vocab


def create_interaction_dataframe(text_tokens, df_vocab, context_size=5):
    token2id = {token: i for i, token in enumerate(df_vocab["token"])}
    token_ids = (token2id.get(token, 0) for token in text_tokens)
    df = pd.DataFrame(list(enumerate(token_ids)), columns=["position", "token_id"])

    # cross join by position for right context only
    df_concat = pd.concat([df.set_index(df["position"] + i + 1) for i in range(context_size)])
    df_co = df_concat.join(df, how="inner", lsuffix="_row", rsuffix="_col")
    df_co = df_co.loc[(df_co["token_id_row"] != df_co["token_id_col"]) &
                      (df_co["position_row"] < df_co["position_col"]), :]
    df_co = df_co.assign(**{"value": 1 / (df_co["position_col"] - df_co["position_row"])})

    # aggregate interactions
    df_agg = (df_co.groupby(["token_id_row", "token_id_col"])["value"]
              .agg(["count", "sum"])
              .reset_index()
              .rename(columns={"token_id_row": "row_token_id", "token_id_col": "col_token_id", "sum": "value"}))
    df_agg = df_agg.loc[(df_agg["count"] != 0) & (df_agg["value"] != 0), :]

    # union swap row and col since symmetric
    dfs_agg = [df_agg, df_agg.rename(columns={"row_token_id": "col_token_id", "col_token_id": "row_token_id"})]
    df_agg = (pd.concat(dfs_agg, sort=False)
              .groupby(["row_token_id", "col_token_id"])
              .sum()
              .reset_index())

    # get vocab info
    df_agg["row_token"] = df_vocab["token"].to_numpy()[df_agg["row_token_id"]]
    df_agg["col_token"] = df_vocab["token"].to_numpy()[df_agg["col_token_id"]]
    df_agg = (df_agg.join(df_vocab.set_index("token"), on="row_token", rsuffix="_row")
              .join(df_vocab.set_index("token"), on="col_token", rsuffix="_col"))
    df_agg["neg_weight"] = df_agg["count_row"] * df_agg["proportion_col"]
    df_agg = df_agg.drop(columns=["count_row", "proportion", "count_col", "proportion_col"])

    # randomise dataframe
    hashes = (df_agg["row_token"]
              .str.cat(df_agg["col_token"], sep=" ")
              .str.encode("utf8")
              .apply(hash))
    df_agg = df_agg.set_index(hashes).sort_index()
    logger.info("interaction dataframe created.")
    logger.info("dataframe shape: %s.", df_agg.shape)
    return df_agg


def create_glove_dataframe(df, count_minimum=10):
    # apply glove transformation
    df = df[df["count"] >= count_minimum]
    df["glove_weight"] = glove_weight(df["count"])
    df["glove_value"] = np.log(df["value"])
    logger.info("dataframe shape: %s.", df.shape)
    return df


def glove_weight(values, alpha=0.75, x_max=100):
    return np.clip(np.power(values / x_max, alpha), 0, 1)


def save_data(data, save_dir="data"):
    # save vocab
    df_vocab = data["vocabulary"]
    csv_path = Path(save_dir, "vocab.csv")
    df_vocab.to_csv(csv_path, index=False)
    logger.info("vocabulary dataframe saved: %s.", csv_path)

    txt_path = Path(save_dir, "vocab.txt")
    txt_path.write_text("\n".join(df_vocab["token"]))
    logger.info("vocabulary saved: %s.", txt_path)

    # save interaction
    df_interaction = data["interaction"]
    csv_path = Path(save_dir, "interaction.csv")
    df_interaction.to_csv(csv_path, index=False)
    logger.info("interaction dataframe saved: %s.", csv_path)

    return data


if __name__ == "__main__":
    parser = ArgumentParser(description="Download, extract and prepare text8 data.")
    parser.add_argument(
        "--url",
        default="http://mattmahoney.net/dc/text8.zip",
        help="url of text8 data (default: %(default)s)"
    )
    parser.add_argument(
        "--dest",
        default="data",
        help="destination directory for downloaded and extracted files (default: %(default)s)"
    )
    parser.add_argument(
        "--vocab-size",
        default=None,
        help="maximum size of vocab (default: %(default)s)"
    )
    parser.add_argument(
        "--coverage",
        type=float,
        default=0.9,
        help="token coverage to set token count cutoff (default: %(default)s)"
    )
    parser.add_argument(
        "--context-size",
        type=int,
        default=5,
        help="size of context window (default: %(default)s)"
    )
    parser.add_argument(
        "--log-path",
        default="main.log",
        help="path of log file (default: %(default)s)"
    )
    args = parser.parse_args()

    logger = get_logger(__name__, log_path=args.log_path, console=True)
    logger.debug("call: %s.", " ".join(sys.argv))
    logger.debug("ArgumentParser: %s.", args)

    try:
        download_data(args.url, args.dest)
        text8 = load_data(args.dest)
        data = process_data(text8, args.vocab_size, args.coverage, args.context_size)
        save_data(data, args.dest)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception(e)
        raise e

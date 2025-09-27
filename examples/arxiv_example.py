import argparse
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_COMPATIBLE_BASE_URL", "http://127.0.0.1:1234/v1")

from agent_ethan.builder import NodeExecutionError, build_agent_from_path


AGENT_CONFIG_PATH = Path(__file__).resolve().parent / "arxiv_agent.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="arXiv agent example")
    parser.add_argument("request", nargs="+", help="検索リクエスト文（必須）")
    parser.add_argument("-p", "--params", dest="params", default=None, help="検索対象論文の条件（今後拡張用）")
    parser.add_argument("-m", "--max-results", dest="max_results", type=int, default=None, help="最大受信件数（検索上限、search_max）")
    parser.add_argument("--selection-max", dest="selection_max", type=int, default=None, help="抽出上限（関連度上位の件数、selection_max）")
    parser.add_argument("--page-size", dest="page_size", type=int, default=None, help="ページサイズ（省略時はデフォルト50）")
    parser.add_argument("--sort-by", dest="sort_by", default=None, choices=["relevance", "lastUpdatedDate", "submittedDate"], help="ソートキー")
    parser.add_argument("--sort-order", dest="sort_order", default=None, choices=["ascending", "descending"], help="ソート順")
    args = parser.parse_args()

    request = " ".join(args.request)

    runtime = build_agent_from_path(str(AGENT_CONFIG_PATH))
    try:
        inputs = {"request": request}
        if args.max_results is not None:
            inputs["search_max"] = args.max_results
        if args.selection_max is not None:
            inputs["selection_max"] = args.selection_max
        if args.page_size is not None:
            inputs["page_size"] = args.page_size
        if args.sort_by is not None:
            inputs["sort_by"] = args.sort_by
        if args.sort_order is not None:
            inputs["sort_order"] = args.sort_order
        # args.params は現状未使用（将来の高度な検索条件向け）
        state = runtime.run(inputs)
    except NodeExecutionError as exc:
        raise SystemExit(
            "LM Studio に接続できませんでした。起動を確認してください。\n"
            f"詳細: {exc}"
        ) from exc

    print("=== Generated Keywords ===")
    print(state.get("keywords"))
    print()

    downloads = state.get("downloads", [])
    if downloads:
        print("=== Downloaded PDFs ===")
        for item in downloads:
            print(f"- {item['id']}: {item['title']} -> {item['path']}")
        print()
    else:
        print("関連する論文をダウンロードできませんでした。\n")

    summary = state.get("summary")
    if summary:
        print("=== Summary ===")
        print(summary)


if __name__ == "__main__":
    main()

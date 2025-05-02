"""Emphasize every 2nd, 4th, ... syllaby per word to make the text easier to read."""

import logging
import re
from pathlib import Path
from typing import List, Optional, Union

import typed_argparse as tap

# Check if dependencies are installed
try:
    from bs4 import BeautifulSoup, Comment, NavigableString, Tag
except ImportError:
    print("Error: BeautifulSoup4 is not installed. Please install using 'pip install beautifulsoup4'")
    exit(1)

try:
    # lxml is recommended for performance and robustness
    import lxml

    PARSER = "lxml"
except ImportError:
    print(
        "Warning: lxml is not installed. Using the slower 'html.parser'."
        " Install lxml with 'pip install lxml' for better performance."
    )
    PARSER = "html.parser"

try:
    from hyphen import Hyphenator, dictools
except ImportError:
    print("Error: PyHyphen is not installed. Please install using 'pip install pyphen'")
    exit(1)


logger = logging.getLogger(__name__)

# --- Constants ---
TARGET_LANG: str = "de_DE"  # Target language for hyphenation (German)
# Tags whose *direct* text content should not be modified
# (Content of nested tags will still be processed unless they are also in this list)
TAGS_TO_SKIP_DIRECT_TEXT: List[str] = ["script", "style", "pre", "code", "textarea"]
# Tags that should be skipped entirely (including all children)
TAGS_TO_SKIP_COMPLETELY: List[str] = ["script", "style"]
DEFAULT_SUFFIX = "_syll_emph"

# --- Core Functions ---


_HYPHENATOR_CACHE: dict[str, Hyphenator] = {}


def get_hyphenator(lang: str) -> Optional[Hyphenator]:
    """
    Initializes the Hyphenator for the specified language.
    Checks if the dictionary exists and attempts to download if necessary.

    Args:
        lang: The language code (e.g., 'de_DE').

    Returns:
        An initialized Hyphenator instance or None if initialization fails.
    """
    global _HYPHENATOR_CACHE
    if lang not in _HYPHENATOR_CACHE:
        try:
            # Check if the dictionary is installed
            if not dictools.is_installed(lang):
                logger.info(f"Hyphenation dictionary for '{lang}' not found.")
                logger.info(f"Attempting to download (requires internet connection)...")
                try:
                    dictools.install(lang)
                    logger.info(f"Dictionary for '{lang}' successfully downloaded/installed.")
                except Exception as e:
                    logger.error(f"Error downloading/installing dictionary for '{lang}': {e}")
                    logger.error("Hyphenation might not work correctly.")
                    return None
            # Initialize
            return Hyphenator(lang)
        except Exception as e:
            logger.error(f"Error initializing the Hyphenator for '{lang}': {e}")
            return None
    return _HYPHENATOR_CACHE.get(lang)


def create_styled_syllables(
    word: str, hyphenator: Hyphenator, soup: BeautifulSoup
) -> List[Union[NavigableString, Tag]]:
    """
    Splits a word into syllables and creates a list of BeautifulSoup elements
    (NavigableString for normal, <b> tag for bold syllables).

    Args:
        word: The word to process.
        hyphenator: The initialized Hyphenator instance.
        soup: The BeautifulSoup object (used to create new tags).

    Returns:
        A list of NavigableString and Tag objects representing the styled word.
    """
    try:
        syllables: List[str] = hyphenator.syllables(word)
    except Exception as e:
        # Fallback if PyHyphen throws an error (rare)
        print(f"Warning: Error during hyphenation for '{word}': {e}. Leaving word unchanged.")
        return [NavigableString(word)]

    if not syllables or len(syllables) <= 1:
        # No syllables found or only one syllable -> no highlighting
        return [NavigableString(word)]

    new_elements: List[Union[NavigableString, Tag]] = []
    for i, syllable in enumerate(syllables):
        if i % 2 == 1:  # Second, fourth, etc., syllable (index 1, 3, ...) -> bold
            bold_tag = soup.new_tag("b")
            bold_tag.string = syllable
            new_elements.append(bold_tag)
        else:  # First, third, etc., syllable (index 0, 2, ...) -> normal
            new_elements.append(NavigableString(syllable))

    return new_elements


def process_text_node(text_node: NavigableString, hyphenator: Hyphenator, soup: BeautifulSoup) -> None:
    """
    Processes a text node: Splits it into words and non-word parts,
    applies syllable formatting to words, and replaces the original node.

    Args:
        text_node: The BeautifulSoup NavigableString node to process.
        hyphenator: The initialized Hyphenator instance.
        soup: The BeautifulSoup object.
    """
    # Regular expression to split the string by word boundaries (\b),
    # capturing both words (\w+) and non-word sequences (\W+).
    # Using (\b\w+\b) is more precise for whole words.
    # The surrounding () capture the delimiters (words) as well.
    parts: List[str] = re.split(r"(\b\w+\b)", text_node.string)
    # Filter out empty strings that can result from the split
    parts = [part for part in parts if part]

    if not parts:
        return  # Nothing to do

    new_content: List[Union[NavigableString, Tag]] = []
    for part in parts:
        # Check if the part is a word (contains alphanumeric characters)
        # We use isalnum() as a simple check. More complex checks could be used
        # if words with hyphens etc. need special handling.
        # len(part) > 1 often avoids single letters or numbers that shouldn't be hyphenated.
        if part.isalnum() and len(part) > 1:
            # Process only words likely to be hyphenated
            styled_syllables = create_styled_syllables(part, hyphenator, soup)
            new_content.extend(styled_syllables)
        else:
            # Not a word (whitespace, punctuation, etc.) -> add unchanged
            new_content.append(NavigableString(part))

    # Replace the original text node with the new sequence of nodes.
    # Using *new_content unpacks the list into individual arguments for replace_with.
    if new_content:
        # Check if the node still exists in the tree before replacing
        if text_node.parent is not None:
            text_node.replace_with(*new_content)
        else:
            # This case should be rare but handles scenarios where the node might have been removed
            # by processing a parent element already.
            print(f"Warning: Text node '{text_node[:20]}...' no longer found in tree, skipping replacement.")


def process_html_content(soup: BeautifulSoup, hyphenator: Hyphenator) -> None:
    """
    Traverses the BeautifulSoup tree and processes all relevant text nodes.

    Args:
        soup: The BeautifulSoup object representing the parsed HTML.
        hyphenator: The initialized Hyphenator instance.
    """
    # Find all text nodes in the document.
    # We iterate over a copy of the list generated by find_all(string=True),
    # because replacing nodes modifies the tree structure we are iterating through.
    all_text_nodes: List[NavigableString] = list(soup.find_all(string=True))

    for text_node in all_text_nodes:
        # Skip comments, CDATA sections, empty strings, etc.
        if isinstance(text_node, (Comment,)) or not text_node.string.strip():
            continue

        # Check the parent tags of the text node
        skip_node = False
        current_parent: Optional[Tag] = text_node.parent
        # Traverse up the tree from the text node's parent
        while current_parent and current_parent.name != "[document]":
            if current_parent.name in TAGS_TO_SKIP_COMPLETELY:
                skip_node = True  # Skip if any ancestor is in the complete skip list
                break
            # Skip direct text content of specific tags, but allow processing of nested tags
            if current_parent.name in TAGS_TO_SKIP_DIRECT_TEXT and text_node.parent == current_parent:
                skip_node = True  # Skip if the immediate parent is in the direct skip list
                break
            current_parent = current_parent.parent  # Move one level up

        if not skip_node:
            # Only process the node if it's not marked for skipping
            process_text_node(text_node, hyphenator, soup)


def process_html_file(input_path: Path, output_path: Path) -> None:
    """
    Main function: Reads an HTML file, processes it, and writes the result.

    Args:
        input_path: Path to the input HTML file.
        output_path: Path where the modified HTML file should be saved.
    """
    logger.debug(f"Processing file: {input_path}")

    # Read HTML file
    try:
        html_content = input_path.read_text()
    except FileNotFoundError as e:
        raise ValueError(f"Error: Input file '{input_path}' not found.") from e
    except Exception as e:
        raise ValueError(f"Error reading input file '{input_path}': {e}") from e

    processed = process_html_file_content(html_content)

    # Ensure the output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(processed)
    logger.debug(f"Processing successful. Result saved to: {output_path}")


def process_html_file_content(html_content: str) -> str:

    logger.debug("Initialize Hyphenator")
    hyphenator = get_hyphenator(TARGET_LANG)
    if hyphenator is None:
        raise RuntimeError(f"Error: Could not initialize Hyphenator for '{TARGET_LANG}'.")

    logger.debug("Parsing HTML content")
    try:
        soup = BeautifulSoup(html_content, PARSER)
    except Exception as e:
        raise ValueError(f"Error parsing HTML: {e}") from e

    logger.debug("Applying syllable highlighting...")
    process_html_content(soup, hyphenator)

    # Generate modified HTML

    # str(soup) generally preserves structure well.
    # soup.prettify() adds unwanted whitespace, in particular it will
    # add whitespace behind behind each closing tag which will result in a
    # space in the output text.
    # The 'html5' formatter generates replacements (like &szlig; for ß),
    # which make it valid html, but invalid xml (since for a valid XML
    # document the entities need to be defined in a Document Type
    # Definition, which is provided in a DOCTYPE stanza befor the <html>
    # tag). Since we cannot guarantee that this is available, rather use
    # minimal:
    # > The default is formatter="minimal". Strings will only be processed
    # > enough to ensure that Beautiful Soup generates valid HTML/XML:
    # This does also generate unwanted whitespace, though, hence use simple
    # str.
    return str(soup)


class Args(tap.TypedArgs):
    """Command-line arguments for the Syllable Highlighter script."""

    input_path: Path = tap.arg(help="Path to the input HTML file.", positional=True)
    inplace: bool = tap.arg(help="Modify the input file in-place.")
    output_path: Path | None = tap.arg(
        help=(
            "Path to save the modified HTML file."
            " If not given (and no inplace operation is requested), based on input name with "
            f" {DEFAULT_SUFFIX} appended."
        ),
        default=None,
    )


def emphasize_file_content(args: Args):
    # Validate input file existence
    if not args.input_path.exists():
        raise ValueError(f"Error: Input file '{args.input_path}' does not exist or is not a file.")

    if args.inplace:
        assert args.output_path is None, "Please specify either an output or inplace."
        output_path = args.input_path
    elif args.output_path is None:
        output_path = args.input_path.parent / (args.input_path.stem + DEFAULT_SUFFIX + ".html")
    else:
        output_path = args.output_path

    input_kind = args.input_path.suffix
    html_input = (".html", ".xhtml")
    if input_kind in html_input:
        process_html_file(args.input_path, output_path)
    else:
        raise ValueError(f"Unable to handle {input_kind} inputs;" f" Supported inputs: {html_input}.")


def main():
    tap.Parser(Args, description=__doc__).bind(emphasize_file_content).run()


if __name__ == "__main__":
    main()

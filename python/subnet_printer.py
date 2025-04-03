# standard imports
from rich.console import Console
from rich.table import Table
from rich.text import Text

# Local imports
import subnet_constants


class RichPrinter:
    _red = "9"
    _green = "10"
    _yellow = "11"

    def __new__(cls, *args, **kwargs):
        if kwargs["print_tables"]:
            return super().__new__(RichTablePrinter)
        else:
            return super().__new__(RichTextPrinter)

    def __init__(self, *args, **kwargs):
        self._console = Console()

        self._netuids = kwargs["netuids"]
        self._validator_data = kwargs["validator_data"]

        self._print_data()

    def _get_style(self, status):
        if status == 2:
            return f"color({self._red})"
        elif status == 1:
                return f"color({self._yellow})"
        else:
            return f"color({self._green})"
    
    def _get_blocks_status(self, blocks):
        return (
            2 if  blocks > subnet_constants.BAD_UPDATED_THRESHOLD
            else 0
        )

    def _get_vtrust_status(self, vtrust, avg_vtrust):
        return (
            2 if avg_vtrust is not None
                and (avg_vtrust - vtrust) > subnet_constants.BAD_VTRUST_THRESHOLD
            else 0
        )

    def _print_data(self):
        raise NotImplementedError


class RichTextPrinter(RichPrinter):
    def _print_data(self):
        text = Text()

        for netuid in self._netuids:
            text.append("\n")
            if netuid not in self._validator_data:
                text.append(
                    f"\nFailed to obtain data for subnet {netuid}",
                    style=self._get_style(2)
                )
                text.append("\n")
                continue

            subnet_data = self._validator_data[netuid]

            if not subnet_data.blocks:
                text.append(
                    f"\nRizzo validator not running on subnet {netuid}",
                    style=self._get_style(2)
                )
                text.append("\n")
                continue

            text.append(f"\nSubnet {netuid} ({subnet_data.subnet_emission:.2f}%):")

            interval_blocks = []
            interval_vtrusts = []
            for subnet_block in subnet_data.block_data:
                blocks = subnet_block.rizzo_updated
                blocks_status = self._get_blocks_status(blocks)
                blocks = str(blocks)

                vtrust = subnet_block.rizzo_vtrust
                avg_vtrust = subnet_block.avg_vtrust
                vtrust_status = self._get_vtrust_status(vtrust, avg_vtrust)
                vtrust = f"{vtrust:.3f}"
        
                max_chars = max(len(blocks), len(vtrust))
                interval_blocks.append((f"{blocks:{max_chars}}", blocks_status))
                interval_vtrusts.append((f"{vtrust:{max_chars}}", vtrust_status))

            text.append("\nUpdated Blocks:")
            for blocks, blocks_status in reversed(interval_blocks):
                text.append(f"  {blocks}", style=self._get_style(blocks_status))
            
            text.append("\nVtrust Values: ")
            for vtrust, vtrust_status in reversed(interval_vtrusts):
                text.append(f"  {vtrust}", style=self._get_style(vtrust_status))

            text.append("\n")
        
        self._console.print(text)


class RichTablePrinter(RichPrinter):
    def _print_data(self):
        failed_text = ""

        for netuid in self._netuids:
            if netuid not in self._validator_data:
                failed_text.append(
                    f"\nFailed to obtain data for subnet {netuid}\n",
                    style=self._get_style(2)
                )
                continue

            subnet_data = self._validator_data[netuid]

            table = Table(title=f"\nSubnet {netuid} ({subnet_data.subnet_emission:.2f}%):")
            table.add_column("", justify="center", no_wrap=True)

            blocks_row = ["Updated"]
            vtrusts_row = ["Vtrust"]

            if not subnet_data.blocks:
                table.add_column("", justify="center", no_wrap=True)
                blocks_row.append(Text("---", style=self._get_style(2)))
                vtrusts_row.append(Text("---", style=self._get_style(2)))
            else:
                for subnet_block in reversed(subnet_data.block_data):
                    table.add_column("", justify="center", no_wrap=True)

                    blocks = subnet_block.rizzo_updated
                    blocks_status = self._get_blocks_status(blocks)
                    blocks_row.append(Text(str(blocks), style=self._get_style(blocks_status)))

                    vtrust = subnet_block.rizzo_vtrust
                    avg_vtrust = subnet_block.avg_vtrust
                    vtrust_status = self._get_vtrust_status(vtrust, avg_vtrust)
                    vtrusts_row.append(Text(f"{vtrust:.3f}", style=self._get_style(vtrust_status)))

            table.add_row(*blocks_row)
            table.add_row(*vtrusts_row)
            self._console.print(table)
            
        self._console.print(failed_text)

#!/usr/bin/env python3

# bittensor import
from bittensor.core.async_subtensor import AsyncSubtensor

# standart imports
import asyncio
from collections import namedtuple
import json
import numpy
import os
import re
import time

# Local imports
from subnet_constants import (
    MIN_STAKE_THRESHOLD,
    MIN_VTRUST_THRESHOLD,
    MAX_U_THRESHOLD,
    RIZZO_COLDKEY,
    MULTI_UID_HOTKEYS,
)


class SubnetDataBase:
    ValidatorData = namedtuple(
        "ValidatorData", [
            "subnet_emission",
            "blocks",
            "block_data",
        ]
    )
    BlockData = namedtuple(
        "BlockData", [
            "rizzo_emission",
            "rizzo_vtrust",
            "avg_vtrust",
            "rizzo_updated",
        ]
    )

    def __init__(self, verbose):
        self._verbose = verbose
        self._validator_data = {}

        # Gather the data for all given subnets
        self._get_subnet_data()

    @property
    def validator_data(self):
        return self._validator_data

    def _get_rizzo_uid(self, metagraph):
        if metagraph.netuid in MULTI_UID_HOTKEYS:
            return metagraph.hotkeys.index(
                MULTI_UID_HOTKEYS[metagraph.netuid]
            )

        return metagraph.coldkeys.index(RIZZO_COLDKEY)

    def _print_verbose(self, message):
        if self._verbose:
            print(message)

    def to_dict(self):
        def serializable(value):
            if isinstance(value, self.BlockData):
                return namedtuple_to_dict(value)
            if isinstance(value, list):
                return [serializable(v) for v in value]
            if isinstance(value, numpy.float32):
                return float(value)
            if isinstance(value, numpy.int64):
                return int(value)
            return value

        def namedtuple_to_dict(data):
            return dict(
                [(f, serializable(getattr(data, f))) for f in data._fields]
            )

        data_dict = {}
        for key in self._validator_data:
            data = self._validator_data[key]
            data_dict[key] = namedtuple_to_dict(data)
        return data_dict

    def _get_subnet_data(self):
        raise NotImplementedError


class SubnetData(SubnetDataBase):
    def __init__(self, netuids, num_intervals, network, existing_data=None, verbose=False):
        self._netuids = netuids
        self._network = network
        self._num_intervals = num_intervals
        self._existing_data = existing_data or {}

        super(SubnetData, self).__init__(verbose)

    def _get_subnet_data(self):
        asyncio.run(self._async_get_subnet_data())

    async def _async_get_subnet_data(self):
        self._print_verbose("\nGathering data")

        # Get subtensor.
        async with AsyncSubtensor(network=self._network) as subtensor:
            max_attempts = 5
            netuids = self._netuids
            for attempt in range(1, max_attempts+1):
                self._print_verbose(f"\nAttempt {attempt} of {max_attempts}")
                await self._get_validator_data(subtensor, netuids)

                # Get netuids missing data
                netuids = list(set(netuids).difference(set(self._validator_data)))
                if netuids:
                    self._print_verbose(
                        "\nFailed to gather data for subnets: "
                        f"{', '.join([str(n) for n in netuids])}."
                    )
                else:
                    break

    async def _get_validator_data(self, subtensor, all_netuids):
        start_time = time.time()
        self._print_verbose(f"\nObtaining data for subnets: {all_netuids}\n")

        # Get the block to pass to async calls so everything is in sync
        block = await subtensor.block

        # Get the metagraphs.
        metagraphs = await asyncio.gather(
            *[
                subtensor.metagraph(netuid=netuid, block=block)
                for netuid in all_netuids
            ]
        )

        block_to_stop = {}
        last_weight_set_block = {}
        for ni, netuid in enumerate(all_netuids):
            metagraph = metagraphs[ni]
            # Get emission percentages.
            subnet_emission = metagraph.emissions.tao_in_emission * 100

            self._validator_data[netuid] = self.ValidatorData(
                subnet_emission=subnet_emission,
                blocks=[],
                block_data=[],
            )

            # Get UID for Rizzo.
            try:
                rizzo_uid = self._get_rizzo_uid(metagraph)
            except ValueError:
                self._print_verbose(
                    f"WARNING: Rizzo validator not running on subnet {netuid}"
                )
                continue

            last_weight_set_block[netuid] = metagraph.last_update[rizzo_uid]

            if self._existing_data.get(netuid):
                block_to_stop[netuid] = (
                    self._existing_data[netuid].blocks[0]
                        if self._existing_data[netuid].blocks
                    else 0  # last_weight_set_block[netuid] - 1
                )
            else:
                block_to_stop[netuid] = 0

        netuids = all_netuids[:]
        for _ in range(self._num_intervals):
            netuids = [
                n for n in netuids
                if n in block_to_stop
                and last_weight_set_block[n] > block_to_stop[n]
            ]

            if not netuids:
                break

            #
            # For some reason this raises random errors:
            #     "Failed to decode type: "scale_info::580" with type id: 580"
            # and it seems non-deterministic.
            # Putting this in a loop.
            #
            metagraphs = {}
            netuids_remaining = netuids[:]
            max_attemps = 3
            for attempt in range(max_attemps):
                self._print_verbose(f"Attempt {attempt+1}: {netuids_remaining}")
                mgs = await asyncio.gather(
                    *[
                        self.get_metagraph_for_netuid_at_block(
                            subtensor, netuid, int(last_weight_set_block[netuid]) - 1
                        )
                        for netuid in netuids_remaining
                    ]
                )
                failed_netuids = []
                for ni, netuid in enumerate(netuids_remaining):
                    if mgs[ni]:
                        metagraphs[netuid] = mgs[ni]
                    else:
                        failed_netuids.append(netuid)
                if not failed_netuids:
                    break
                netuids_remaining = failed_netuids

            for netuid in netuids:
                if netuid not in metagraphs:
                    self._print_verbose(
                        f"Unable to obtain all {self._num_intervals} "
                        f"weight setting intervals for subnet {netuid}."
                    )
                    del block_to_stop[netuid]
                    continue

                metagraph = metagraphs[netuid]
                if not metagraph:
                    self._print_verbose(
                        f"Unable to obtain all {self._num_intervals} "
                        f"weight setting intervals for subnet {netuid}."
                    )
                    del block_to_stop[netuid]
                    continue

                # Get UID for Rizzo.
                try:
                    rizzo_uid = self._get_rizzo_uid(metagraph)
                except ValueError:
                    self._print_verbose(
                        f"Unable to obtain all {self._num_intervals} "
                        f"weight setting intervals for subnet {netuid}."
                    )
                    del block_to_stop[netuid]
                    continue

                # There's some weirdness going on with sn72. Catching it here.
                try:
                    prev_weight_set_block = metagraph.last_update[rizzo_uid]
                    interval = last_weight_set_block[netuid] - prev_weight_set_block
                    rizzo_vtrust = metagraph.Tv[rizzo_uid]
                    rizzo_emission = metagraph.E[rizzo_uid]

                    # Get all validator uids that have valid stake amount
                    all_uids = [
                        i for (i, s) in enumerate(metagraph.S)
                        if i != rizzo_uid and s > MIN_STAKE_THRESHOLD
                    ]
                    # Get all validators that have proper VT and U
                    valid_uids = [
                        i for i in all_uids
                        if (metagraph.Tv[i] > MIN_VTRUST_THRESHOLD)
                        & (
                            last_weight_set_block[netuid] - metagraph.last_update[i]
                            < MAX_U_THRESHOLD
                        )
                    ]

                    if not valid_uids:
                        avg_vtrust = None
                    else:
                        # Get min/max/average vTrust values.
                        # vtrusts = [metagraph.Tv[uid] for uid in valid_uids]
                        avg_vtrust = numpy.average(metagraph.Tv[valid_uids])
                except IndexError:
                    self._print_verbose(
                        f"Unable to obtain all {self._num_intervals} "
                        f"weight setting intervals for subnet {netuid}."
                    )
                    del block_to_stop[netuid]
                    continue

                block_data = self.BlockData(
                    rizzo_emission=rizzo_emission,
                    rizzo_vtrust=rizzo_vtrust,
                    avg_vtrust=avg_vtrust,
                    rizzo_updated=interval,
                )
                self._validator_data[netuid].blocks.append(last_weight_set_block[netuid])
                self._validator_data[netuid].block_data.append(block_data)

                last_weight_set_block[netuid] = prev_weight_set_block

        for netuid in all_netuids:
            if self._existing_data.get(netuid):
                self._validator_data[netuid].blocks.extend(
                    self._existing_data[netuid].blocks
                )
                self._validator_data[netuid].block_data.extend(
                    self._existing_data[netuid].block_data
                )
                if len(self._validator_data[netuid].blocks) > self._num_intervals:
                    self._validator_data[netuid] = self.ValidatorData(
                        subnet_emission=self._validator_data[netuid].subnet_emission,
                        blocks=self._validator_data[netuid].blocks[:self._num_intervals],
                        block_data=self._validator_data[netuid].block_data[:self._num_intervals],
                    )

        total_time = time.time() - start_time
        self._print_verbose(
            f"Subnet data gathered in {int(total_time)} seconds."
        )

    async def get_metagraph_for_netuid_at_block(self, subtensor, netuid, block):
        #
        # For some reason this raises random errors:
        #     "Failed to decode type: "scale_info::580" with type id: 580"
        # and it seems non-deterministic.
        # Putting this in a loop.
        #
        max_attemps = 3
        for attempt in range(max_attemps):
            try:
                return await subtensor.metagraph(
                    netuid=netuid, block=int(block)
                )
            except Exception as err:
                self._print_verbose(
                    f"failed attempt: {attempt+1}, netuid: {netuid}, block: {block}, error: {err}"
                )
                error = err
        self._print_verbose(
            f"Error could not obtain metagraph for netuid {netuid} at block {block} "
            f"after {max_attemps} attempts: {error}"
        )
        return None


class SubnetDataFromJson(SubnetDataBase):
    json_file_name = "validator_data.json"

    def __init__(self, netuids, json_folder, num_intervals=None, verbose=False):
        self._netuids = netuids
        self._json_folder = json_folder
        self._num_intervals = num_intervals

        super(SubnetDataFromJson, self).__init__(verbose)

    @classmethod
    def get_json_file_name(cls, netuid):
        json_base, json_ext = os.path.splitext(cls.json_file_name)
        return f"{json_base}.{netuid}{json_ext}"

    @classmethod
    def get_netuids_from_json_folder(cls, json_folder):
        netuids = []
        json_file_pattern = cls.get_json_file_name(r"(?P<netuid>\d+)")
        json_file_pattern = json_file_pattern.replace(".", r"\.")
        json_file_regex = re.compile(rf"^{json_file_pattern}$")
        for _file in os.listdir(json_folder):
            regex_match = json_file_regex.match(_file)
            if regex_match:
                netuids.append(int(regex_match.group("netuid")))

        return sorted(netuids)

    def _get_subnet_data(self):
        for netuid in self._netuids:
            self._validator_data[netuid] = self.ValidatorData(
                subnet_emission=None,
                blocks=[],
                block_data=[],
            )

            json_file = os.path.join(
                self._json_folder, self.get_json_file_name(netuid)
            )
            if not os.path.isfile(json_file):
                self._print_verbose(
                    f"Existing json file ({json_file}) for netuid "
                    f"{netuid} does not exist."
                )
                continue

            self._print_verbose(
                f"Obtaining existing data from json file ({json_file}) "
                f"for netuid {netuid}."
            )

            with open(json_file, "r") as fd:
                subnet_data = json.load(fd)

            subnet_data = subnet_data[str(netuid)]

            block_data = []
            for subnet_block_data in subnet_data["block_data"]:
                block_data.append(
                    self.BlockData(
                        rizzo_emission=subnet_block_data["rizzo_emission"],
                        rizzo_vtrust=subnet_block_data["rizzo_vtrust"],
                        avg_vtrust=subnet_block_data["avg_vtrust"],
                        rizzo_updated=subnet_block_data["rizzo_updated"],
                    )
                )
            if self._num_intervals:
                self._validator_data[netuid] = self.ValidatorData(
                    subnet_emission=subnet_data["subnet_emission"],
                    blocks=subnet_data["blocks"][:self._num_intervals],
                    block_data=block_data[:self._num_intervals],
                )
            else:
                self._validator_data[netuid] = self.ValidatorData(
                    subnet_emission=subnet_data["subnet_emission"],
                    blocks=subnet_data["blocks"],
                    block_data=block_data,
                )

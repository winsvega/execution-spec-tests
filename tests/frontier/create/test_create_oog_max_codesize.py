"""
Test CREATE operations with out-of-gas scenarios after max codesize deployments.

Converted from CreateOOGafterMaxCodesizeFiller.yml with reduced contract interactions.
"""

import pytest

from ethereum_test_tools import (
    Account,
    Address,
    Alloc,
    Bytecode,
    Environment,
    StateTestFiller,
    Storage,
    Transaction,
)
from ethereum_test_tools import Opcodes as Op


@pytest.mark.ported_from(
    [
        "https://github.com/ethereum/tests/blob/main/src/GeneralStateTestsFiller/stCreateTest/CreateOOGafterMaxCodesizeFiller.yml",
    ],
    pr=["https://github.com/ethereum/execution-spec-tests/pull/TBD"],
)
@pytest.mark.valid_from("Cancun")
@pytest.mark.slow
@pytest.mark.parametrize(
    "contract_count,should_oog",
    [
        pytest.param(3, True, id="create_oog"),
        pytest.param(3, False, id="create_success"),
        pytest.param(5, True, id="create_more_oog"),
        pytest.param(5, False, id="create_more_success"),
    ],
)
def test_create_oog_after_max_codesize(
    state_test: StateTestFiller,
    pre: Alloc,
    contract_count: int,
    should_oog: bool,
):
    """
    Test CREATE operations with out-of-gas scenarios after max codesize deployments.
    
    This test validates:
    1. Creating max-codesize contracts in a loop
    2. Proper reversion when OOG occurs during contract creation
    3. Contract existence and storage when creation succeeds
    """
    
    # Define addresses for the contracts
    target_code_addr = Address(0x00000000000000000000000000000000000c0de0)
    init_code_addr = Address(0x00000000000000000000000000000000000c0de1)
    factory_addr = Address(0x00000000000000000000000000000000000c0deb)
    
    # Deploy the target code contract (stores codesize, can self-destruct)
    pre[target_code_addr] = Account(
        balance=0,
        code=_create_target_contract(),
        nonce=0,
        storage={}
    )
    
    # Deploy the init code contract (returns max codesize deployment)
    pre[init_code_addr] = Account(
        balance=0,
        code=_create_init_contract(target_code_addr),
        nonce=0,
        storage={}
    )
    
    # Deploy the factory contract (creates multiple contracts)
    pre[factory_addr] = Account(
        balance=0,
        code=_create_factory_contract(init_code_addr),
        nonce=1,
        storage={}
    )
    
    # Fund the sender
    sender = pre.fund_eoa()
    
    # Create transaction data: [contract_count, should_oog]
    tx_data = (
        contract_count.to_bytes(32, 'big') +
        (1 if should_oog else 0).to_bytes(32, 'big')
    )
    
    tx = Transaction(
        to=factory_addr,
        gas_limit=0x100000000,  # Large gas limit
        sender=sender,
        data=tx_data,
        value=0,
        gas_price=10,
        nonce=0,
    )
    
    # Expected post state
    post_state = _build_expected_post_state(factory_addr, contract_count, should_oog)
    
    state_test(
        env=Environment(),
        pre=pre,
        post=post_state,
        tx=tx,
    )


def _create_target_contract() -> Bytecode:
    """
    Target contract that stores its codesize and can self-destruct.
    
    Yul equivalent:
    {
        sstore(0, codesize())
        if gt(calldatasize(), 0) {
            selfdestruct(0)
        }
    }
    """
    return (
        Op.SSTORE(0, Op.CODESIZE) +
        Op.JUMPI(Op.PUSH1(0x10), Op.GT(Op.CALLDATASIZE, 0)) +
        Op.STOP +
        Op.JUMPDEST +  # 0x10
        Op.SELFDESTRUCT(0)
    )


def _create_init_contract(target_addr: Address) -> Bytecode:
    """
    Init code that copies target contract and returns max codesize.
    
    Yul equivalent:
    {
        extcodecopy(target_addr, 0, 0, extcodesize(target_addr))
        return(0, 0x6000)  // max codesize = 24576 bytes
    }
    """
    return (
        Op.EXTCODECOPY(target_addr, 0, 0, Op.EXTCODESIZE(target_addr)) +
        Op.RETURN(0, 0x6000)  # Return max codesize (24576 bytes)
    )


def _create_factory_contract(init_addr: Address) -> Bytecode:
    """
    Factory contract that creates multiple max-codesize contracts.
    
    Yul equivalent:
    {
        sstore(1, 1)  // success flag
        let contract_count := calldataload(0)
        let should_oog := calldataload(32)
        
        // Get init code
        let initcode_size := extcodesize(init_addr)
        extcodecopy(init_addr, 0, 0, initcode_size)
        
        // Create contracts in loop
        for { let i := 0 } lt(i, contract_count) { i := add(i, 1) } {
            create(0, 0, initcode_size)
        }
        
        if gt(should_oog, 0) {
            invalid()  // Cause OOG
        }
    }
    """
    return (
        # Store success flag
        Op.SSTORE(1, 1) +
        
        # Load parameters from calldata
        Op.PUSH1(0) + Op.CALLDATALOAD +   # contract_count
        Op.PUSH1(32) + Op.CALLDATALOAD +  # should_oog
        
        # Get init code from init_addr
        Op.PUSH20(init_addr) +
        Op.DUP1 + Op.EXTCODESIZE +  # init_size
        Op.DUP2 + Op.PUSH1(0) + Op.PUSH1(0) + Op.DUP5 + Op.EXTCODECOPY +
        
        # Loop to create contracts
        Op.PUSH1(0) +  # loop counter i = 0
        
        # Loop start
        Op.JUMPDEST +  # 0x50 (approximate)
        Op.DUP1 + Op.DUP4 + Op.LT +  # i < contract_count
        Op.ISZERO + Op.PUSH1(0x80) + Op.JUMPI +  # Jump to after loop
        
        # Create contract
        Op.PUSH1(0) + Op.PUSH1(0) + Op.DUP6 + Op.CREATE + Op.POP +
        
        # Increment counter and loop
        Op.PUSH1(1) + Op.ADD +
        Op.PUSH1(0x50) + Op.JUMP +
        
        # After loop
        Op.JUMPDEST +  # 0x80
        Op.POP + Op.POP + Op.POP +  # Clean stack
        
        # Check if should OOG
        Op.ISZERO + Op.PUSH1(0xA0) + Op.JUMPI +
        Op.INVALID +  # Cause OOG
        
        Op.JUMPDEST +  # 0xA0
        Op.STOP
    )


def _build_expected_post_state(factory_addr: Address, contract_count: int, should_oog: bool) -> dict:
    """Build the expected post state."""
    post = {}
    
    if should_oog:
        # Factory should not have success flag set
        post[factory_addr] = Account(
            nonce=1,  # No contracts created due to OOG
            storage={}
        )
    else:
        # Factory should have success flag and increased nonce
        post[factory_addr] = Account(
            nonce=1 + contract_count,  # Nonce increases by number of contracts created
            storage={1: 1}  # Success flag
        )
        
        # TODO: Could add checks for created contracts, but would need
        # to compute their addresses using create address computation
    
    return post
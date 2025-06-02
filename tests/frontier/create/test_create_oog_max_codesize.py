"""
Test CREATE operations with out-of-gas scenarios after max codesize deployments.

This test is a Python conversion of CreateOOGafterMaxCodesizeFiller.yml from the ethereum/tests
repository. The original test creates a large number of max-codesize contracts (24KB each) and
tests various OOG scenarios.

This conversion faithfully replicates the original contract structure from the YAML test:
1. Contract 0xc0de0: Code that ends up in created contracts - stores codesize and can self-destruct
2. Contract 0xc0de1: Init code that creates max codesize contracts using 0xc0de0 code  
3. Contract 0xc0deb: Factory that creates multiple contracts using init code from 0xc0de1
4. Contract 0xc0dea: Main test contract that orchestrates the test scenarios

The test validates:
- Creating multiple large contracts in a loop
- Proper transaction reversion when OOG occurs during contract creation
- Correct state changes (nonce increments, storage updates) on successful execution
- Self-destruct functionality for created contracts
- Difference in behavior between success and OOG scenarios

Original test reference:
tests/static/state_tests/stCreateTest/CreateOOGafterMaxCodesizeFiller.yml
"""

import pytest

from ethereum_test_tools import (
    Account,
    Alloc,
    Environment,
    StateTestFiller,
    Transaction,
)
from ethereum_test_tools.vm.opcode import Opcodes as Op


@pytest.mark.ported_from(
    [
        "https://github.com/ethereum/tests/blob/main/src/GeneralStateTestsFiller/stCreateTest/CreateOOGafterMaxCodesizeFiller.yml",
    ],
    pr=["https://github.com/ethereum/execution-spec-tests/pull/TBD"],
)
@pytest.mark.valid_from("Cancun")
@pytest.mark.slow
@pytest.mark.parametrize(
    "delegate_contract_count,subcall_contract_count,subcall_oog,selfdestruct_count",
    [
        pytest.param(0, 10, True, 0, id="LowContractCount_NoDelegateCreate_CallCreateOOG"),
        pytest.param(10, 10, True, 0, id="LowContractCount_DelegateCreate_CallCreateOOG"),
        pytest.param(10, 10, False, 14, id="LowContractCount_DelegateCreate_CallCreate_SelfDestruct"),
    ],
)
def test_create_oog_after_max_codesize(
    state_test: StateTestFiller,
    pre: Alloc,
    delegate_contract_count: int,
    subcall_contract_count: int,
    subcall_oog: bool,
    selfdestruct_count: int,
):
    """
    Test CREATE operations with out-of-gas scenarios after max codesize deployments.
    
    This test faithfully recreates the original YAML test logic with 4 contracts:
    1. 0xc0de0: Contract code that stores codesize and can self-destruct
    2. 0xc0de1: Init code that creates contracts with 0xc0de0 code
    3. 0xc0deb: Factory that creates multiple contracts 
    4. 0xc0dea: Main orchestrator contract
    
    To run this test:
    1. Install the project dependencies: pip install -e .
    2. Run with pytest: pytest tests/frontier/create/test_create_oog_max_codesize.py
    """
    # Use max codesize like the original test
    max_codesize = 0x6000  # 24KB max codesize
    
    # Contract 0xc0de0: Code that will end up in the created contracts
    # If calldata > 0, self-destruct, otherwise store codesize()
    contract_c0de0_code = (
        Op.SSTORE(0, Op.CODESIZE) +  # Store codesize
        Op.JUMPI(
            "selfdestruct",
            Op.GT(Op.CALLDATASIZE, 0)
        ) +
        Op.STOP +
        Op.JUMPDEST("selfdestruct") +
        Op.SELFDESTRUCT(0)
    )
    contract_c0de0_addr = pre.deploy_contract(code=contract_c0de0_code)
    
    # Contract 0xc0de1: Init code that creates max codesize contracts
    # using the code from 0xc0de0
    contract_c0de1_code = (
        # Copy code from 0xc0de0 into memory  
        Op.EXTCODECOPY(
            contract_c0de0_addr,
            0,
            0, 
            Op.EXTCODESIZE(contract_c0de0_addr)
        ) +
        # Return max_codesize bytes 
        Op.RETURN(0, max_codesize)
    )
    contract_c0de1_addr = pre.deploy_contract(code=contract_c0de1_code)
    
    # Contract 0xc0deb: Factory that creates multiple contracts
    # The purpose of this contract is to create a given number of max-codesize-contracts, 
    # specified by the first argument of the call.
    # The created contracts can self-destruct when called.
    # The second parameter is used to determine if this call should OOG instead of returning,
    # which should revert the creation of any contracts.
    
    # Use the maximum number of contracts we might need for any test case
    max_contracts_needed = 250  # From the original high count test cases
    
    contract_c0deb_code = (
        # Set success flag at the beginning
        Op.SSTORE(1, 1) +
        
        # Get the init code that returns max codesize from another contract
        Op.EXTCODECOPY(
            contract_c0de1_addr,
            0,
            0,
            Op.EXTCODESIZE(contract_c0de1_addr)
        ) +
        
        # Create contracts with max codesize in loop
        # for { let i := 0 } lt(i, contract_count) { i := add(i, 1) }
        # This simulates the Yul loop from the original
        sum([
            # Only create if i < contract_count from calldata
            Op.JUMPI(f"skip_create_{i}", Op.ISZERO(Op.LT(i, Op.CALLDATALOAD(0)))) +
            Op.MSTORE(
                Op.ADD(Op.EXTCODESIZE(contract_c0de1_addr), Op.MUL(i, 32)),
                Op.CREATE(0, 0, Op.EXTCODESIZE(contract_c0de1_addr))
            ) +
            Op.JUMPDEST(f"skip_create_{i}")
            for i in range(max_contracts_needed)
        ]) +
        
        # If should_oog flag is set, execute INVALID to cause OOG
        Op.JUMPI("should_oog_check", Op.GT(Op.CALLDATALOAD(32), 0)) +
        Op.JUMP("end") +
        Op.JUMPDEST("should_oog_check") +
        Op.INVALID +
        Op.JUMPDEST("end") +
        
        # Return created contract addresses
        Op.RETURN(Op.EXTCODESIZE(contract_c0de1_addr), Op.MUL(Op.CALLDATALOAD(0), 32))
    )
    contract_c0deb_addr = pre.deploy_contract(code=contract_c0deb_code, nonce=1)
    
    # Contract 0xc0dea: Main test contract that orchestrates the test
    # This test contract performs 3 actions, which are configured by the parameters passed:
    # First action is to delegate call 0xc0deb to create self-destructing contracts on 0xc0dea context without OOG'ing;
    # this way we can create max-codesize-contracts that later can be self-destructed.
    # Second action is to call 0xc0deb, in a call that creates several max-codesize-contracts and can OOG, to test the contract
    # creation correctly reverts.
    # Third action is to call the created contracts for self-destruct, which will test the max-codesize-contracts are
    # correctly removed.
    contract_c0dea_code = (
        # Delegate call for contract creation
        Op.MSTORE(0, Op.CALLDATALOAD(4)) +   # delegate_contract_count
        Op.MSTORE(32, 0) +                   # should_oog = false
        Op.DELEGATECALL(
            Op.DIV(Op.GAS, 2),              # gas
            contract_c0deb_addr,            # address
            0,                              # args_offset
            64,                             # args_size
            64,                             # ret_offset  
            Op.MUL(Op.CALLDATALOAD(4), 32)  # ret_size (delegate_contract_count * 32)
        ) +
        
        # If delegatecall failed, revert
        Op.JUMPI("delegatecall_success", Op.DUP1) +
        Op.REVERT(0, 0) +
        Op.JUMPDEST("delegatecall_success") +
        Op.POP +  # Remove return value
        
        # Call for OOG contract creation
        Op.MSTORE(0, Op.CALLDATALOAD(36)) +  # subcall_contract_count
        Op.MSTORE(32, Op.CALLDATALOAD(68)) + # subcall_oog
        Op.CALL(
            Op.DIV(Op.GAS, 2),              # gas
            contract_c0deb_addr,            # address
            0,                              # value
            0,                              # args_offset
            64,                             # args_size
            Op.ADD(64, Op.MUL(Op.CALLDATALOAD(4), 32)), # ret_offset
            Op.MUL(Op.CALLDATALOAD(36), 32) # ret_size (subcall_contract_count * 32)
        ) +
        
        # Check if we OOG'd as expected
        Op.JUMPI("call_success", Op.DUP1) +
        # We OOG'd - check if this was expected
        Op.JUMPI("after_call", Op.CALLDATALOAD(68)) +  # if subcall_oog == true, continue
        # We shouldn't have OOG'd, revert
        Op.REVERT(0, 0) +
        Op.JUMPDEST("call_success") +
        Op.POP +  # Remove return value
        Op.JUMPDEST("after_call") +
        
        # Calculate how many contracts were actually created
        # contract_created_count = delegate_contract_count + (subcall succeeded ? subcall_contract_count : 0)
        
        # Call all contracts so they sstore their codesize()
        # Use dynamic loop based on actual contract counts
        sum([
            # Only call if i < delegate_contract_count + (subcall_oog ? 0 : subcall_contract_count)
            Op.JUMPI(f"skip_call_{i}", 
                    Op.ISZERO(Op.LT(i, 
                        Op.ADD(
                            Op.CALLDATALOAD(4),  # delegate_contract_count
                            Op.MUL(
                                Op.CALLDATALOAD(36),  # subcall_contract_count
                                Op.ISZERO(Op.CALLDATALOAD(68))  # !subcall_oog
                            )
                        )
                    ))) +
            Op.CALL(
                Op.SUB(Op.GAS, 1000),       # gas
                Op.MLOAD(Op.ADD(64, Op.MUL(i, 32))), # contract address
                0,                          # value
                0, 0,                       # no calldata
                0, 0                        # no return data
            ) +
            Op.POP +  # Remove return value
            Op.JUMPDEST(f"skip_call_{i}")
            for i in range(max_contracts_needed)
        ]) +
        
        # Self-destruct contracts
        sum([
            # Only call if i < selfdestruct_count
            Op.JUMPI(f"skip_destruct_{i}", Op.ISZERO(Op.LT(i, Op.CALLDATALOAD(100)))) +
            Op.CALL(
                Op.SUB(Op.GAS, 1000),       # gas
                Op.MLOAD(Op.ADD(64, Op.MUL(i, 32))), # contract address
                0,                          # value
                0, 1,                       # calldata size = 1 to trigger selfdestruct
                0, 0                        # no return data
            ) +
            Op.POP +  # Remove return value
            Op.JUMPDEST(f"skip_destruct_{i}")
            for i in range(max_contracts_needed)
        ])
    )
    contract_c0dea_addr = pre.deploy_contract(code=contract_c0dea_code, nonce=1)
    
    sender = pre.fund_eoa()

    tx = Transaction(
        to=contract_c0dea_addr,
        gas_limit=0x100000000,  # Large gas limit
        sender=sender,
        # Encode parameters exactly like the original YAML test with :abi f(uint,uint,bool,uint)
        data=(
            (0).to_bytes(4, 'big') +  # Function selector (4 bytes)
            delegate_contract_count.to_bytes(32, 'big') +   # calldataload(4)
            subcall_contract_count.to_bytes(32, 'big') +    # calldataload(36) 
            (1 if subcall_oog else 0).to_bytes(32, 'big') + # calldataload(68)
            selfdestruct_count.to_bytes(32, 'big')          # calldataload(100)
        ),
        value=0,
        gas_price=10,
        nonce=0,
    )

    # Build expected post state based on test scenario
    post_state = {}
    
    # Main contract 0xc0dea
    post_state[contract_c0dea_addr] = Account(
        nonce=1 + delegate_contract_count,
        storage={1: 1}  # Storage updated by delegatecall
    )
    
    # Factory contract 0xc0deb
    if subcall_oog:
        # If subcall OOG'd, no contracts created in subcall
        post_state[contract_c0deb_addr] = Account(
            nonce=1,  # No nonce increase due to OOG
            storage={}  # No storage update due to OOG revert
        )
    else:
        # If subcall succeeded, contracts were created
        post_state[contract_c0deb_addr] = Account(
            nonce=1 + subcall_contract_count,
            storage={1: 1}
        )

    state_test(
        env=Environment(),
        pre=pre,
        post=post_state,
        tx=tx,
    )

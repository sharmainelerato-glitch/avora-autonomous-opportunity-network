/* AVORA testnet wallet connector using the user-controlled Meteor browser wallet.
   Requires the official Meteor extension with a TESTNET account selected.
   AVORA never requests, receives, or stores private keys or recovery phrases. */
import { setupWalletSelector, actionCreators } from '@near-wallet-selector/core';
import { setupMeteorWallet } from '@near-wallet-selector/meteor-wallet';

const NEAR_RE = /^(?=.{2,64}$)[a-z0-9][a-z0-9_.-]*\.testnet$/;
let selectorPromise;
async function selector(){
  if (!selectorPromise) {
    selectorPromise=setupWalletSelector({
      network:'testnet',
      modules:[setupMeteorWallet()],
    }).catch(error=>{ selectorPromise=null; throw error; });
  }
  return selectorPromise;
}
async function wallet(){ return (await selector()).wallet('meteor-wallet'); }
async function connected(){
  const accounts=await (await wallet()).getAccounts();
  return accounts?.[0]?.accountId || null;
}
async function connect(){
  const w=await wallet();
  const existing=await w.getAccounts();
  if (existing?.[0]?.accountId) return existing[0].accountId;
  // This contractId is the sample testnet account used by Wallet Selector
  // for sign-in compatibility; AVORA does not call or deploy it.
  const accounts=await w.signIn({contractId:'test.testnet'});
  const accountId=accounts?.[0]?.accountId || await connected();
  if (!accountId) {
    throw new Error('No account connected. Install/unlock the Meteor Wallet extension, switch to NEAR TESTNET, and approve AVORA in the wallet.');
  }
  if (!NEAR_RE.test(accountId)) {
    throw new Error('The connected account is not a NEAR testnet account. Switch Meteor Wallet to TESTNET.');
  }
  return accountId;
}
async function disconnect(){ await (await wallet()).signOut(); return true; }
async function transferApproved({recipient,amountYocto,callbackUrl}){
  if (!NEAR_RE.test(recipient)) throw new Error('Invalid testnet recipient');
  const amount=BigInt(amountYocto);
  if(amount<=0n || amount>1000000000000000000000000n) throw new Error('Amount exceeds the 1 NEAR/testnet payment limit');
  const w=await wallet();
  const accounts=await w.getAccounts();
  if(!accounts?.length)throw new Error('Connect the Meteor NEAR testnet wallet first');
  const signer=accounts[0].accountId;
  if(!NEAR_RE.test(signer))throw new Error('Wallet signer is not a NEAR testnet account');
  const result=await w.signAndSendTransaction({
    signerId:signer,
    receiverId:recipient,
    actions:[actionCreators.transfer(amount)],
    callbackUrl:callbackUrl || window.location.origin+'/#/near',
  });
  return {signer,transactionHash:result?.transaction?.hash||null,redirected:!result};
}
window.avoraNearWallet={connect,disconnect,connected,transferApproved};

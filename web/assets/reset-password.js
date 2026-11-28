import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.57.4/+esm";
const form=document.getElementById("reset-form");
const button=document.getElementById("reset-submit");
const message=document.getElementById("reset-message");
function show(text,kind="error"){message.textContent=text;message.dataset.kind=kind;}
async function init(){
  try{
    const response=await fetch("/api/config",{cache:"no-store"});
    if(!response.ok) throw new Error("Could not load account service.");
    const config=await response.json();
    if(!config.configured) throw new Error("Account service is not configured.");
    const supabase=createClient(config.supabase_url,config.publishable_key,{auth:{flowType:"pkce",detectSessionInUrl:true,persistSession:true,autoRefreshToken:true}});
    const params=new URLSearchParams(location.search);
    const code=params.get("code");
    if(code){const {error}=await supabase.auth.exchangeCodeForSession(code);if(error) throw error;}
    const {data,error}=await supabase.auth.getSession();
    if(error) throw error;
    if(!data.session) throw new Error("This reset link is invalid or has expired. Request a new one from the sign-in page.");
    form.addEventListener("submit",async event=>{
      event.preventDefault();
      const password=document.getElementById("new-password").value;
      const confirm=document.getElementById("confirm-password").value;
      if(password.length<8) return show("Use at least 8 characters.");
      if(password!==confirm) return show("The passwords do not match.");
      button.disabled=true;button.textContent="Updating password…";
      try{
        const {error}=await supabase.auth.updateUser({password});
        if(error) throw error;
        show("Password updated. You can now sign in with your new password.","success");
        setTimeout(()=>location.replace("/signin"),1200);
      }catch(error){show(error?.message||"Could not update password.");}
      finally{button.disabled=false;button.textContent="Save new password";}
    });
  }catch(error){show(error?.message||"Password reset could not start.");}
}
init();
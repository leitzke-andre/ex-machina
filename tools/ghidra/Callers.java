import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.util.*;
public class Callers extends GhidraScript {
  public void run() throws Exception {
    FunctionManager fm=currentProgram.getFunctionManager();
    for(String a:getScriptArgs()){
      long v=Long.parseLong(a,16);
      TreeSet<String> s=new TreeSet<>();
      ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(toAddr(v));
      while(it.hasNext()){Reference r=it.next();Function f=fm.getFunctionContaining(r.getFromAddress());s.add(r.getFromAddress()+"("+r.getReferenceType()+")@"+(f==null?"-":f.getEntryPoint().toString()));}
      println("CALLERS "+a+" : "+s);
    }
  }
}

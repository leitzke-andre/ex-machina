import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.*;
public class Dis extends GhidraScript {
  public void run() throws Exception {
    Memory_fix();
    FunctionManager fm=currentProgram.getFunctionManager();
    byte[] b=new byte[(int)currentProgram.getMemory().getBlocks()[0].getSize()];
    currentProgram.getMemory().getBytes(toAddr(0x08003000L),b);
    Register tm=currentProgram.getLanguage().getRegister("TMode");
    int made=0;
    for(int i=0;i<0x5d00-2;i+=2){
      int h=(b[i]&0xff)|((b[i+1]&0xff)<<8);
      if((h&0xff00)==0xb500 || (h==0xe92d)){ // push {..,lr}
        Address a=toAddr(0x08003000L+i);
        if(fm.getFunctionAt(a)==null && currentProgram.getListing().getInstructionContaining(a)==null){
          try{ currentProgram.getProgramContext().setValue(tm,a,a,java.math.BigInteger.ONE);
          if(disassemble(a)){ createFunction(a,null); made++; } }catch(Exception e){}
        }
      }
    }
    println("MADE "+made+" total "+fm.getFunctionCount());
    Address t=toAddr(0x080085a2L);
    Function f=fm.getFunctionContaining(t);
    println("FUNC "+f);
    DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
    if(f!=null) println("DECOMP\n"+di.decompileFunction(f,60,monitor).getDecompiledFunction().getC());
  }
  void Memory_fix(){}
}
